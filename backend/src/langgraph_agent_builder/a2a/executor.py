"""LabAgentExecutor — the A2A ⇄ LangGraph bridge (SPEC §7.6–§7.8, normative).

contextId == thread_id (scoped per client for public agents), one task == one
run + its interrupt-resume chain, interrupt → input-required, follow-up message
→ Command(resume=…), terminal result → one `response` artifact.

a2a-sdk 1.x (protocol v1.0) types are protobuf: ``Part`` is a flat message with a
``content`` oneof (``text`` str / ``data`` Value / ``raw`` bytes / ``url`` str);
there are no ``TextPart``/``DataPart``/``FilePart`` classes — parts are built with
``a2a.helpers.new_text_part``/``new_data_part`` and read via ``WhichOneof``.
``TaskUpdater.update_status`` no longer takes ``final=`` (finality is derived from
the state / the stream ending), so input-required uses ``updater.requires_input``.
Errors are raised as ``a2a.utils.errors`` ``A2AError`` subclasses directly (no
``ServerError`` wrapper); the REST transport maps them to google.rpc shapes.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from a2a.helpers import new_data_part, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Task, TaskState, TaskStatus
from a2a.utils.errors import ContentTypeNotSupportedError, InvalidParamsError
from google.protobuf.json_format import MessageToDict

from langgraph_agent_builder.a2a.scope import resolve_client_scope
from langgraph_agent_builder.a2a.tasks import TERMINAL_STATES, state_to_str
from langgraph_agent_builder.runtime.executor import Executor, RunResult
from langgraph_agent_builder.schema.events import RunEvent
from langgraph_agent_builder.sdk.interrupts import parse_approval_resume, parse_input_resume
from langgraph_agent_builder.services.orchestrator import Orchestrator, scoped_thread_id
from langgraph_agent_builder.services.settings import Settings

logger = logging.getLogger("langgraph_agent_builder.a2a.executor")

STATUS_THROTTLE_S = 0.5  # max 2/s working updates (SPEC §7.8)


def _mime_allowed(mime: str, allowlist: str) -> bool:
    patterns = [p.strip() for p in allowlist.split(",") if p.strip()]
    return any(fnmatch.fnmatch(mime, p) for p in patterns)


class LabAgentExecutor(AgentExecutor):
    def __init__(
        self,
        *,
        spec_provider: Callable[[], Awaitable[dict[str, Any]]],  # pinned served FlowSpec
        flow_slug: str,
        orchestrator: Orchestrator,
        executor: Executor,
        settings: Settings,
        files_service: Any = None,
        public: bool = True,
        stream_tokens: bool = True,
    ) -> None:
        self._spec_provider = spec_provider
        self._flow_slug = flow_slug
        self._orchestrator = orchestrator
        self._executor = executor
        self._settings = settings
        self._files = files_service
        self._public = public
        self._stream_tokens = stream_tokens

    # ------------------------------------------------------------ helpers
    def _thread_id(self, context_id: str, scope: str) -> str:
        if self._public:
            return scoped_thread_id(scope, context_id)
        return context_id

    @staticmethod
    def _parts(context: RequestContext) -> list[Any]:
        return list(context.message.parts) if context.message else []

    def _validate_parts(self, context: RequestContext) -> None:
        """File-part mime allowlist (SPEC §7.8) — side-effect-free, raises
        ContentTypeNotSupported. Inline (``raw``) and referenced (``url``) parts
        are the v1.0 file parts."""
        for part in self._parts(context):
            if part.WhichOneof("content") in ("raw", "url"):
                mime = part.media_type or "application/octet-stream"
                if not _mime_allowed(mime, self._settings.a2a_accepted_mime):
                    raise ContentTypeNotSupportedError(message=f"mime type {mime!r} not accepted")

    async def _inbound(self, context: RequestContext) -> dict[str, Any]:
        """Message parts → run input (SPEC §7.8 inbound); parts pre-validated."""
        text_parts: list[str] = []
        data: dict[str, Any] = {}
        files: list[dict[str, Any]] = []
        for part in self._parts(context):
            kind = part.WhichOneof("content")
            if kind == "text":
                text_parts.append(part.text)
            elif kind == "data":
                value = MessageToDict(part.data)
                data.update(value if isinstance(value, dict) else {"value": value})
            elif kind == "raw":  # inline file bytes (v1.0 FileWithBytes)
                mime = part.media_type or "application/octet-stream"
                if self._files is not None:
                    saved = await self._files.save(part.filename or "upload", mime, part.raw)
                    files.append({"file_id": saved["file_id"], "mime": mime, "name": saved["name"]})
            elif kind == "url":  # file by reference (v1.0 FileWithUri)
                mime = part.media_type or "application/octet-stream"
                files.append(
                    {"file_id": "", "mime": mime, "name": part.filename or "", "uri": part.url}
                )
        return {
            "input_text": "\n".join(t for t in text_parts if t),
            "data": {"a2a_input": data} if data else None,
            "files": files,
        }

    def _check_output_modes(self, context: RequestContext) -> None:
        config = context.configuration
        accepted = list(config.accepted_output_modes) if config else []
        if not accepted:
            return
        ours = {"text/plain", "application/json", "text/*", "application/*", "*/*"}
        if not any(a in ours or a.split("/")[0] + "/*" in ours for a in accepted):
            raise ContentTypeNotSupportedError(
                message=f"acceptedOutputModes {accepted} not supported "
                "(text/plain, application/json)"
            )

    # ------------------------------------------------------------ execute steps
    @staticmethod
    def _new_task(context: RequestContext) -> Task:
        """Initial submitted Task; ``id`` MUST equal the RequestContext task_id
        (the handler validates the match)."""
        message = context.message
        assert message is not None
        return Task(
            id=context.task_id or message.task_id or str(uuid.uuid4()),
            context_id=context.context_id or message.context_id or str(uuid.uuid4()),
            status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            history=[message],
        )

    async def _ensure_task(self, context: RequestContext, event_queue: EventQueue) -> Task | None:
        """Create or reuse the task; None ⇒ messageId dedup hit (prior result
        re-enqueued, SPEC §7.5)."""
        task = context.current_task
        if task is None:
            if context.message is None:
                raise InvalidParamsError(message="neither task nor message provided")
            task = self._new_task(context)
            await event_queue.enqueue_event(task)
            return task
        if task.status.state in TERMINAL_STATES:
            raise InvalidParamsError(
                message=f"task {task.id} is {state_to_str(task.status.state)}; terminal tasks "
                "cannot be restarted — send a new message without taskId"
            )
        msg_id = context.message.message_id if context.message else ""
        if msg_id and task.history and any(m.message_id == msg_id for m in task.history[:-1]):
            await event_queue.enqueue_event(task)
            return None
        return task

    def _resolve_resume_payload(
        self, payload: dict[str, Any], context: RequestContext, inbound: dict[str, Any]
    ) -> Any:
        """Client answer → Command(resume=…) payload; None ⇒ unparseable (§7.7)."""
        client_value: Any = None
        for part in self._parts(context):
            if part.WhichOneof("content") == "data":
                client_value = MessageToDict(part.data)
                break
        if client_value is None:
            client_value = inbound["input_text"]
        kind = payload.get("kind")
        if kind == "approval":
            return parse_approval_resume(
                client_value, payload.get("options") or ["approve", "reject"]
            )
        if kind == "free_text":
            return parse_input_resume(client_value, payload.get("schema"))
        return client_value

    @staticmethod
    async def _reprompt_unparsed(updater: TaskUpdater, payload: dict[str, Any]) -> None:
        """Unparseable answer: stay input-required, explain accepted answers (§7.7)."""
        options = payload.get("options") or []
        hint = (
            f"Could not parse your answer. Accepted answers: {', '.join(options)}."
            if options
            else "Could not parse your answer against the expected schema."
        )
        await updater.requires_input(
            message=updater.new_agent_message(parts=[new_text_part(hint), new_data_part(payload)])
        )

    async def _ensure_run_row(self, run_id: str, thread_id: str) -> None:
        if await self._orchestrator.runs.get(run_id) is None:
            await self._orchestrator.runs.create(
                run_id, thread_id=thread_id, mode="a2a", flow_slug=self._flow_slug
            )

    @staticmethod
    async def _emit_terminal(result: RunResult, updater: TaskUpdater, sink: _A2ASink) -> None:
        """RunResult → terminal protocol event (SPEC §7.6/§7.8/§7.10)."""
        await sink.flush_tokens(last=result.status == "completed")

        if result.status == "input_required":
            payload = result.interrupt or {}
            prompt = str(payload.get("prompt", "input required"))
            await updater.requires_input(
                message=updater.new_agent_message(
                    parts=[new_text_part(prompt), new_data_part(payload)]
                )
            )
            return
        if result.status == "failed":
            parts = [
                new_text_part(
                    f"{result.error_code or 'error'}: {result.error_message or 'run failed'}"
                )
            ]
            if result.error_code:
                # machine-readable RT code (§7.10: data.run_error_code)
                parts.append(new_data_part({"run_error_code": result.error_code}))
            await updater.failed(message=updater.new_agent_message(parts=parts))
            return
        if result.status == "cancelled":
            # the canceled status is enqueued by cancel(); the run task is already
            # unwinding — a second terminal event here would be redundant.
            return

        parts = [new_text_part(result.result_text)]
        if result.result_json is not None:
            parts.append(new_data_part(result.result_json))
        await updater.add_artifact(parts, name="response")
        await updater.complete()

    # ------------------------------------------------------------ execute
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # negotiation/part validation BEFORE task creation: a content-type error
        # must not orphan a freshly-enqueued task in `submitted` (SPEC §7.10).
        # These raise A2AError subclasses that the REST transport maps to 4xx.
        self._check_output_modes(context)
        self._validate_parts(context)

        task = await self._ensure_task(context, event_queue)
        if task is None:
            return  # messageId dedup — prior result already re-enqueued (§7.5)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        scope = resolve_client_scope(getattr(context, "call_context", None))
        thread_id = self._thread_id(task.context_id or task.id, scope)
        compiled = await self._orchestrator.compiled(await self._spec_provider())
        if not compiled.ok:
            await updater.failed(
                message=updater.new_agent_message(parts=[new_text_part("flow has compile errors")])
            )
            return

        inbound = await self._inbound(context)
        pending = await self._executor.pending_interrupt(compiled, thread_id)
        resume_payload: Any = None
        if pending is not None:
            resume_payload = self._resolve_resume_payload(pending, context, inbound)
            if resume_payload is None:
                await self._reprompt_unparsed(updater, pending)
                return
            bus = self._executor.bus
            if bus is not None:
                # restart-proof resume (§6.2): the bus's in-memory seq counters
                # are gone after a restart — continue numbering above the
                # persisted events, or every post-resume event collides with
                # uq_run_event_seq (dropped by the persist loop) and live SSE
                # tails filter the run's remaining events as already-replayed
                bus.set_seq_floor(task.id, await self._orchestrator.runs.max_seq(task.id))

        await self._ensure_run_row(task.id, thread_id)
        await updater.start_work()

        sink = _A2ASink(updater, stream_tokens=self._stream_tokens)
        try:
            result: RunResult = await self._executor.execute(
                compiled,
                run_id=task.id,
                thread_id=thread_id,
                mode="a2a",
                input_text=inbound["input_text"],
                data=inbound["data"],
                files=inbound["files"],
                resume=resume_payload if pending is not None else None,
                event_sink=sink,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # sanitized failure (SPEC §7.6/§7.10): the traceback stays in the
            # server log; remote clients get a generic message, never str(exc)
            logger.exception("a2a task %s failed unexpectedly", task.id)
            await updater.failed(
                message=updater.new_agent_message(parts=[new_text_part("internal error")])
            )
            return

        await self._emit_terminal(result, updater, sink)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            return
        # enqueue the canceled status BEFORE signaling the run to stop: the run
        # task is being cancelled underneath us and its producer closes the event
        # queue as it unwinds — a late enqueue could miss the drain window and
        # leave the task reporting `working`. `Executor.cancel` is non-awaiting
        # by contract (awaiting it deadlocks against this same consumer).
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.cancel()
        await self._executor.cancel(task.id)


class _A2ASink:
    """RunEvent → A2A stream translation (working updates + token artifacts)."""

    def __init__(self, updater: TaskUpdater, stream_tokens: bool) -> None:
        self._updater = updater
        self._stream_tokens = stream_tokens
        self._last_status = 0.0
        self._token_buffer: list[str] = []
        self._streamed_any = False

    async def __call__(self, event: RunEvent) -> None:
        kind = event.event
        if kind == "node_token":
            if self._stream_tokens:
                self._token_buffer.append(str(event.data.get("delta", "")))
                if sum(len(t) for t in self._token_buffer) >= 80:
                    await self.flush_tokens()
            return
        if kind in (
            "run_started",
            "run_resumed",
            "run_finished",
            "run_cancelled",
            "interrupt_raised",
        ):
            return  # protocol states cover these
        if kind == "node_status":
            now = time.monotonic()
            if now - self._last_status < STATUS_THROTTLE_S:
                return
            self._last_status = now
        await self._updater.update_status(
            TaskState.TASK_STATE_WORKING,
            message=self._updater.new_agent_message(
                parts=[
                    new_data_part(
                        {
                            "type": kind,
                            "node": event.data.get("node_id", ""),
                            "data": {k: v for k, v in event.data.items() if k != "node_id"},
                        }
                    )
                ]
            ),
        )

    async def flush_tokens(self, last: bool = False) -> None:
        if not self._stream_tokens:
            return
        text = "".join(self._token_buffer)
        self._token_buffer.clear()
        if not text and not (last and self._streamed_any):
            return
        await self._updater.add_artifact(
            [new_text_part(text)],
            artifact_id="response-stream",
            name="response-stream",
            append=self._streamed_any,
            last_chunk=last,
        )
        self._streamed_any = True
