"""LGAAgentExecutor — the A2A ⇄ LangGraph bridge (SPEC §7.6–§7.8, normative).

contextId == thread_id (scoped per client for public agents), one task == one
run + its interrupt-resume chain, interrupt → input-required (final), follow-up
message → Command(resume=…), terminal result → one `response` artifact.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    ContentTypeNotSupportedError,
    DataPart,
    FilePart,
    FileWithBytes,
    FileWithUri,
    InvalidParamsError,
    Part,
    TaskState,
    TextPart,
)
from a2a.utils import new_task
from a2a.utils.errors import ServerError

from lga.runtime.executor import Executor, RunResult
from lga.schema.events import RunEvent
from lga.sdk.interrupts import parse_approval_resume, parse_input_resume
from lga.services.orchestrator import Orchestrator, scoped_thread_id
from lga.services.settings import Settings

logger = logging.getLogger("lga.a2a.executor")

TERMINAL = {
    TaskState.completed,
    TaskState.failed,
    TaskState.canceled,
    TaskState.rejected,
}
STATUS_THROTTLE_S = 0.5  # max 2/s working updates (SPEC §7.8)


def _mime_allowed(mime: str, allowlist: str) -> bool:
    patterns = [p.strip() for p in allowlist.split(",") if p.strip()]
    return any(fnmatch.fnmatch(mime, p) for p in patterns)


class LGAAgentExecutor(AgentExecutor):
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
    def _client_scope(self, context: RequestContext) -> str:
        call_ctx = getattr(context, "call_context", None)
        if call_ctx is not None and getattr(call_ctx, "state", None):
            value = call_ctx.state.get("lga_client_scope")
            if value:
                return str(value)
        from lga.a2a.scope import current_client_scope

        return current_client_scope.get()

    def _thread_id(self, context_id: str, scope: str) -> str:
        if self._public:
            return scoped_thread_id(scope, context_id)
        return context_id

    async def _inbound(self, context: RequestContext) -> dict[str, Any]:
        """Message parts → run input (SPEC §7.8 inbound)."""
        text_parts: list[str] = []
        data: dict[str, Any] = {}
        files: list[dict[str, Any]] = []
        for part in (context.message.parts if context.message else []) or []:
            root = part.root
            if isinstance(root, TextPart):
                text_parts.append(root.text)
            elif isinstance(root, DataPart):
                data.update(root.data if isinstance(root.data, dict) else {"value": root.data})
            elif isinstance(root, FilePart):
                file = root.file
                mime = getattr(file, "mime_type", None) or "application/octet-stream"
                if not _mime_allowed(mime, self._settings.a2a_accepted_mime):
                    raise ServerError(
                        error=ContentTypeNotSupportedError(
                            message=f"mime type {mime!r} not accepted"
                        )
                    )
                if isinstance(file, FileWithBytes) and self._files is not None:
                    import base64

                    saved = await self._files.save(
                        getattr(file, "name", "upload") or "upload",
                        mime,
                        base64.b64decode(file.bytes),
                    )
                    files.append({"file_id": saved["file_id"], "mime": mime, "name": saved["name"]})
                elif isinstance(file, FileWithUri):
                    files.append(
                        {
                            "file_id": "",
                            "mime": mime,
                            "name": getattr(file, "name", "") or "",
                            "uri": file.uri,
                        }
                    )
        return {
            "input_text": "\n".join(t for t in text_parts if t),
            "data": {"a2a_input": data} if data else None,
            "files": files,
        }

    def _check_output_modes(self, context: RequestContext) -> None:
        config = getattr(context, "configuration", None)
        accepted = getattr(config, "accepted_output_modes", None) if config else None
        if not accepted:
            return
        ours = {"text/plain", "application/json", "text/*", "application/*", "*/*"}
        if not any(a in ours or a.split("/")[0] + "/*" in ours for a in accepted):
            raise ServerError(
                error=ContentTypeNotSupportedError(
                    message=f"acceptedOutputModes {accepted} not supported "
                    "(text/plain, application/json)"
                )
            )

    # ------------------------------------------------------------ execute
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            if context.message is None:
                raise ServerError(
                    error=InvalidParamsError(message="neither task nor message provided")
                )
            task = new_task(context.message)
            await event_queue.enqueue_event(task)
        elif task.status.state in TERMINAL:
            raise ServerError(
                error=InvalidParamsError(
                    message=f"task {task.id} is {task.status.state.value}; terminal tasks "
                    "cannot be restarted — send a new message without taskId"
                )
            )

        # messageId dedup (SPEC §7.5): same messageId on this task ⇒ prior result
        msg_id = context.message.message_id if context.message else None
        if msg_id and task.history:
            if any(m.message_id == msg_id for m in task.history[:-1]):
                await event_queue.enqueue_event(task)
                return

        self._check_output_modes(context)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        scope = self._client_scope(context)
        thread_id = self._thread_id(task.context_id or task.id, scope)
        spec = await self._spec_provider()
        compiled = await self._orchestrator.compiled(spec)
        if not compiled.ok:
            await updater.failed(
                message=updater.new_agent_message(
                    parts=[Part(root=TextPart(text="flow has compile errors"))]
                )
            )
            return

        # resume vs new run: does the thread hold a pending interrupt?
        checkpointer = await self._executor._get_checkpointer()
        graph = compiled.compile(checkpointer=checkpointer)
        snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        pending = [i for t in (snapshot.tasks or ()) for i in (t.interrupts or ())]

        inbound = await self._inbound(context)
        resume_payload: Any = None
        if pending:
            raw = pending[0].value if pending else {}
            payload = raw if isinstance(raw, dict) else {}
            kind = payload.get("kind")
            client_value: Any = None
            for part in (context.message.parts if context.message else []) or []:
                if isinstance(part.root, DataPart):
                    client_value = part.root.data
                    break
            if client_value is None:
                client_value = inbound["input_text"]
            if kind == "approval":
                resume_payload = parse_approval_resume(
                    client_value, payload.get("options") or ["approve", "reject"]
                )
            elif kind == "free_text":
                resume_payload = parse_input_resume(client_value, payload.get("schema"))
            else:
                resume_payload = client_value
            if resume_payload is None:
                # unparseable answer: stay input-required, explain accepted answers
                options = payload.get("options") or []
                hint = (
                    f"Could not parse your answer. Accepted answers: {', '.join(options)}."
                    if options
                    else "Could not parse your answer against the expected schema."
                )
                await updater.update_status(
                    TaskState.input_required,
                    message=updater.new_agent_message(
                        parts=[Part(root=TextPart(text=hint)), Part(root=DataPart(data=payload))]
                    ),
                    final=True,
                )
                return

        run_row = await self._orchestrator.runs.get(task.id)
        if run_row is None:
            await self._orchestrator.runs.create(
                task.id, thread_id=thread_id, mode="a2a", flow_slug=self._flow_slug
            )

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
                resume=resume_payload if pending else None,
                event_sink=sink,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # sanitized failure (SPEC §7.6)
            logger.exception("a2a task %s failed unexpectedly", task.id)
            await updater.failed(
                message=updater.new_agent_message(
                    parts=[Part(root=TextPart(text=f"internal error: {exc}"))]
                )
            )
            return

        await sink.flush_tokens(last=result.status == "completed")

        if result.status == "input_required":
            payload = result.interrupt or {}
            prompt = str(payload.get("prompt", "input required"))
            await updater.update_status(
                TaskState.input_required,
                message=updater.new_agent_message(
                    parts=[Part(root=TextPart(text=prompt)), Part(root=DataPart(data=payload))]
                ),
                final=True,
            )
            return
        if result.status == "failed":
            await updater.failed(
                message=updater.new_agent_message(
                    parts=[
                        Part(
                            root=TextPart(
                                text=f"{result.error_code or 'error'}: "
                                f"{result.error_message or 'run failed'}"
                            )
                        )
                    ]
                )
            )
            return
        if result.status == "cancelled":
            # the canceled status event is enqueued by cancel() on the cancel
            # queue; emitting a second, final one here would trigger the sdk
            # consumer's immediate-close which wipes tapped child queues
            return

        parts: list[Part] = [Part(root=TextPart(text=result.result_text))]
        if result.result_json is not None:
            parts.append(Part(root=DataPart(data=result.result_json)))
        await updater.add_artifact(parts, name="response")
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            return
        # enqueue the canceled status FIRST: stopping the run below closes the
        # producer's queue, which cascades to the tapped cancel queue — a late
        # enqueue would be dropped and the aggregator would report `working`.
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
        if kind in ("run_started", "run_resumed", "run_finished", "interrupt_raised"):
            return  # protocol states cover these
        if kind == "node_status":
            now = time.monotonic()
            if now - self._last_status < STATUS_THROTTLE_S:
                return
            self._last_status = now
        await self._updater.update_status(
            TaskState.working,
            message=self._updater.new_agent_message(
                parts=[
                    Part(
                        root=DataPart(
                            data={
                                "type": kind,
                                "node": event.data.get("node_id", ""),
                                "data": {k: v for k, v in event.data.items() if k != "node_id"},
                            }
                        )
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
            [Part(root=TextPart(text=text))],
            artifact_id="response-stream",
            name="response-stream",
            append=self._streamed_any,
            last_chunk=last,
        )
        self._streamed_any = True
