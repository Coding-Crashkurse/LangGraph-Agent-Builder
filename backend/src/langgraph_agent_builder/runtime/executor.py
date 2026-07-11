"""Run orchestration: execute/resume/cancel/debug (SPEC §6.1).

All run modes (playground/api/debug/a2a/mcp) share this executor.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from pydantic import BaseModel
from ulid import ULID

from langgraph_agent_builder.compiler import CompiledFlow
from langgraph_agent_builder.runtime.streams import EventBus
from langgraph_agent_builder.schema.diagnostics import RuntimeError_, RuntimeErrorCode
from langgraph_agent_builder.schema.events import RunEvent
from langgraph_agent_builder.schema.scrub import scrub_data
from langgraph_agent_builder.schema.state import initial_state
from langgraph_agent_builder.sdk.component import NodeKind
from langgraph_agent_builder.sdk.ports import Message
from langgraph_agent_builder.sdk.runtime import RUN_CTX_KEY, RunContext
from langgraph_agent_builder.sdk.templating import message_text

logger = logging.getLogger("lab.executor")

StatusHook = Callable[..., Awaitable[None]]

EventSink = Callable[[RunEvent], Awaitable[None]]

# Sync sink for the per-node run timeline (REFACTOR.md §7): the compiler node
# wrapper calls it (via RunContext) with a plain payload dict; the payload we
# forward carries ``run_id`` so RunService can key the row. Sync + fire-and-
# forget (it enqueues to a background writer) so it never blocks the hot path.
NodeRunRecorder = Callable[[dict[str, Any]], None]


class RunResult(BaseModel):
    run_id: str
    thread_id: str
    status: str
    result_text: str = ""
    result_json: dict[str, Any] | None = None
    interrupt: dict[str, Any] | None = None
    interrupt_node: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    node_id: str | None = None  # failing node — every RT error carries it (§5.6)


@dataclass
class RunHandle:
    run_id: str
    thread_id: str
    flow_slug: str
    mode: str
    run_context: RunContext
    task: asyncio.Task[Any] | None = None
    result: RunResult | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)


def _value_to_result(value: Any) -> tuple[str, Any]:
    """One output value → ``(text, structured|None)`` (SPEC §7.8/§8.1).

    Shared by the ``until_node`` and terminal branches so they cannot drift.
    Message/``str`` stay text-only; a ``dict`` (Json) is its own structuredContent;
    a ``list`` (Table — an ``is_list`` port) is wrapped as ``{"rows": [...]}``
    because MCP ``structuredContent`` and A2A DataParts must be JSON objects.
    Anything else degrades to ``str`` with no structured payload.
    """
    if isinstance(value, Message):
        return value.content, None
    if isinstance(value, str):
        return value, None
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, default=str), value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, default=str), {"rows": value}
    return str(value), None


def extract_result(
    compiled: CompiledFlow, state_values: dict[str, Any], until_node: str | None = None
) -> tuple[str, Any]:
    """Terminal (or ``until_node``) result → (text, structured|None) (SPEC §7.8/§6.4)."""
    ports_map = state_values.get("ports") or {}
    assert compiled.ir is not None
    if until_node is not None:
        target = compiled.ir.nodes.get(until_node)
        if target is not None:
            for out_name in target.outputs:
                value = ports_map.get(f"{until_node}.{out_name}")
                if value is not None:
                    return _value_to_result(value)
        return "", None
    for node in compiled.ir.nodes.values():
        if node.kind != NodeKind.TERMINAL:
            continue
        for out_name in node.outputs:
            value = ports_map.get(f"{node.id}.{out_name}")
            if value is not None:
                return _value_to_result(value)
    # fallback: last assistant message
    msgs = [m for m in state_values.get("messages") or [] if getattr(m, "type", "") == "ai"]
    return (message_text(msgs[-1]) if msgs else ""), None


class Executor:
    def __init__(
        self,
        *,
        checkpointer_getter: Callable[[], Awaitable[Any]],
        bus: EventBus | None = None,
        on_status: StatusHook | None = None,
        record_node_run: NodeRunRecorder | None = None,
        recursion_limit_default: int = 50,
        preview_length: int = 300,  # LAB_MAX_TEXT_LENGTH
    ) -> None:
        self._get_checkpointer = checkpointer_getter
        self._bus = bus
        self._on_status = on_status
        self._record_node_run = record_node_run
        self._recursion_default = recursion_limit_default
        self._preview_length = preview_length
        self.runs: dict[str, RunHandle] = {}

    def _attach_node_recorder(self, ctx: RunContext, run_id: str) -> None:
        """Give a run's RunContext a per-run node-timeline recorder (REFACTOR.md §7).

        Mirrors how ``on_status`` is wired: the executor owns the sink, and here
        closes it over ``run_id`` so the compiler wrapper stays DB-free. No-op
        when no sink is configured or the context already has one (e.g. resume).
        """
        sink = self._record_node_run
        if sink is None or ctx._noop or ctx.record_node_run is not None:
            return

        def record(payload: dict[str, Any]) -> None:
            sink({"run_id": run_id, **payload})

        ctx.record_node_run = record

    @property
    def bus(self) -> EventBus | None:
        """The process event bus, when wired (SPEC §6.2)."""
        return self._bus

    async def get_checkpointer(self) -> Any:
        """The tier-selected checkpointer every run uses (SPEC §6.3).

        Public so thread-state/debug/A2A code can compile graphs against the
        same saver without reaching into Executor internals.
        """
        return await self._get_checkpointer()

    async def pending_interrupt(
        self, compiled: CompiledFlow, thread_id: str
    ) -> dict[str, Any] | None:
        """The thread's pending interrupt payload, if any (SPEC §7.7).

        Public seam for the resume-vs-new-run decision (the A2A bridge and any
        other caller inspecting a parked HITL thread): reads the same
        checkpointer every run uses. A non-dict interrupt value degrades to
        ``{}`` so callers can treat the result as a payload dict.
        """
        checkpointer = await self._get_checkpointer()
        graph = compiled.compile(checkpointer=checkpointer)
        snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        pending = [i for t in (snapshot.tasks or ()) for i in (t.interrupts or ())]
        if not pending:
            return None
        raw = pending[0].value
        return raw if isinstance(raw, dict) else {}

    # ---------------------------------------------------------------- events
    async def _emit(
        self,
        sink: EventSink | None,
        run_id: str,
        thread_id: str,
        event: str,
        data: dict[str, Any],
    ) -> None:
        run_event = RunEvent(event=event, run_id=run_id, thread_id=thread_id, data=data)
        if self._bus is not None:
            # the bus scrubs secrets (§10.5) and assigns seq; the sink gets the
            # same redacted event object — scrubbed exactly once
            run_event = self._bus.publish(run_event)
        else:
            run_event.data = scrub_data(run_event.data)
        if sink is not None:
            try:
                await sink(run_event)
            except Exception:
                logger.exception("event sink failed for %s", event)

    async def _status(self, run_id: str, status: str, **kw: Any) -> None:
        if self._on_status is not None:
            try:
                await self._on_status(run_id=run_id, status=status, **kw)
            except Exception:
                logger.exception("status hook failed for run %s", run_id)

    # ---------------------------------------------------------------- main
    async def execute(
        self,
        compiled: CompiledFlow,
        *,
        run_id: str | None = None,
        thread_id: str | None = None,
        mode: str = "api",
        input_text: str = "",
        data: dict[str, Any] | None = None,
        files: list[dict[str, Any]] | None = None,
        messages: list[Any] | None = None,
        resume: Any = None,
        debug: bool = False,
        debug_action: str | None = None,  # "step" | "continue" on a paused debug run
        until_node: str | None = None,  # partial run (SPEC §6.4)
        register: bool = True,
        run_context: RunContext | None = None,
        event_sink: EventSink | None = None,
        handle: RunHandle | None = None,  # start() passes its pre-registered handle
    ) -> RunResult:
        """Run to completion or interrupt. Returns the RunResult either way."""
        if handle is None:
            run_id = run_id or str(ULID()).lower()
            thread_id = thread_id or str(ULID()).lower()
            handle = RunHandle(
                run_id=run_id,
                thread_id=thread_id,
                flow_slug=compiled.spec.flow.slug,
                mode=mode,
                run_context=run_context
                or RunContext(run_id=run_id, thread_id=thread_id, mode=mode),
            )
        handle.task = handle.task or asyncio.current_task()
        # attach the node-timeline recorder here so both execute() and start()
        # (which delegates here with its pre-built handle) get it exactly once
        self._attach_node_recorder(handle.run_context, handle.run_id)
        if register:
            self.runs[handle.run_id] = handle
        try:
            result = await self._execute_inner(
                compiled,
                handle,
                input_text=input_text,
                data=data,
                files=files,
                messages=messages,
                resume=resume,
                debug=debug,
                debug_action=debug_action,
                until_node=until_node,
                event_sink=event_sink,
            )
        except asyncio.CancelledError:
            # bus only, no sink: the A2A bridge enqueues its own canceled status
            # in cancel() — a second final event would trip the sdk queue wipe
            result = await self._finish(
                handle,
                None,
                "cancelled",
                error_code=RuntimeErrorCode.RT104.value,
                message="run cancelled",
            )
            # swallow only if cancellation was requested through cancel();
            # otherwise propagate so callers see the cancellation
            if not handle.run_context.cancellation.is_set():
                handle.result = result
                handle.done.set()
                raise
        finally:
            if register:
                self.runs.pop(handle.run_id, None)
        handle.result = result
        handle.done.set()
        return result

    async def _execute_inner(
        self,
        compiled: CompiledFlow,
        handle: RunHandle,
        *,
        input_text: str,
        data: dict[str, Any] | None,
        files: list[dict[str, Any]] | None,
        messages: list[Any] | None,
        resume: Any,
        debug: bool,
        debug_action: str | None = None,
        until_node: str | None = None,
        event_sink: EventSink | None = None,
    ) -> RunResult:
        run_id, thread_id = handle.run_id, handle.thread_id
        last_started_node = ""
        node_error_emitted = False
        try:
            if until_node is not None:
                from langgraph_agent_builder.compiler.subgraph import induce_subgraph

                compiled = induce_subgraph(compiled, until_node)
            checkpointer = await self._get_checkpointer()
            graph = compiled.compile(checkpointer=checkpointer)
            config: RunnableConfig = {
                "configurable": {"thread_id": thread_id, RUN_CTX_KEY: handle.run_context},
                "recursion_limit": compiled.spec.flow.settings.recursion_limit
                or self._recursion_default,
            }
            graph_input, debug = await self._resolve_graph_input(
                compiled,
                handle,
                event_sink,
                input_text=input_text,
                data=data,
                files=files,
                messages=messages,
                resume=resume,
                debug=debug,
                debug_action=debug_action,
            )
            # debug mode pauses before every node (SPEC §6.1)
            interrupt_before: Literal["*"] | None = "*" if debug else None
            await self._status(run_id, "running")

            interrupt_payload: dict[str, Any] | None = None
            interrupt_node: str | None = None
            conflict_step = -1
            conflict_writers: dict[str, str] = {}
            # durable checkpoints written asynchronously (SPEC §6.3): the flagship
            # HITL/resume story needs state persisted, but off the run's hot path.
            # "debug" is tapped only for task_result step numbers: this langgraph
            # yields updates one chunk per task, so RT101's superstep grouping
            # has to come from somewhere else.
            async for stream_mode, chunk in graph.astream(
                graph_input,
                config,
                stream_mode=["custom", "updates", "debug"],
                durability="async",
                interrupt_before=interrupt_before,
            ):
                if stream_mode == "custom" and isinstance(chunk, dict):
                    event = str(chunk.get("event") or "custom")
                    node_id = str(chunk.get("node_id") or "")
                    if event == "node_started":
                        last_started_node = node_id
                    elif event == "node_error":
                        node_error_emitted = True
                    await self._emit(
                        event_sink,
                        run_id,
                        thread_id,
                        event,
                        {"node_id": node_id, **(chunk.get("data") or {})},
                    )
                elif stream_mode == "updates" and isinstance(chunk, dict):
                    if "__interrupt__" in chunk:
                        interrupts = chunk["__interrupt__"]
                        if not interrupts:
                            # static pause from interrupt_before (debug mode):
                            # no dynamic payload — the post-loop snapshot.next
                            # branch reports the debug_step
                            continue
                        raw = interrupts[0].value
                        interrupt_payload = raw if isinstance(raw, dict) else {"value": raw}
                        interrupt_node = last_started_node or None
                        # do NOT break: closing the generator early can cancel
                        # langgraph's async checkpoint flush — on Postgres the
                        # interrupt would then be missing when the resume
                        # request inspects the thread state
                        continue
                elif stream_mode == "debug" and isinstance(chunk, dict):
                    if chunk.get("type") == "task_result":
                        step = int(chunk.get("step") or 0)
                        if step != conflict_step:
                            conflict_step, conflict_writers = step, {}
                        payload = chunk.get("payload") or {}
                        delta = payload.get("result")
                        if isinstance(delta, dict):
                            self._check_data_conflicts(
                                conflict_writers, str(payload.get("name") or ""), delta
                            )

            if interrupt_payload is not None:
                await self._status(run_id, "input_required")
                await self._emit(
                    event_sink,
                    run_id,
                    thread_id,
                    "interrupt_raised",
                    {"node_id": interrupt_node or "", "payload": interrupt_payload},
                )
                return RunResult(
                    run_id=run_id,
                    thread_id=thread_id,
                    status="input_required",
                    interrupt=interrupt_payload,
                    interrupt_node=interrupt_node,
                )

            snapshot = await graph.aget_state(config)
            # debug mode pauses before every node — surface as paused interrupt
            if debug and snapshot.next:
                await self._status(run_id, "input_required")
                await self._emit(
                    event_sink,
                    run_id,
                    thread_id,
                    "interrupt_raised",
                    {"node_id": snapshot.next[0], "payload": {"kind": "debug_step"}},
                )
                return RunResult(
                    run_id=run_id,
                    thread_id=thread_id,
                    status="input_required",
                    interrupt={"kind": "debug_step", "next": list(snapshot.next)},
                    interrupt_node=snapshot.next[0],
                )
            text, structured = extract_result(compiled, snapshot.values or {}, until_node)
            return await self._finish(
                handle, event_sink, "completed", text=text, structured=structured
            )
        except RuntimeError_ as exc:
            err_node = exc.node_id or last_started_node or None
            if err_node and not node_error_emitted:
                # RT101/RT102/RT107 reach here without a node_error from the node
                # wrapper (only RT103 emits one) — SPEC §5.6 wants every RT error
                # on the event stream
                await self._emit(
                    event_sink,
                    run_id,
                    thread_id,
                    "node_error",
                    {"node_id": err_node, "code": exc.code.value, "message": str(exc)},
                )
            return await self._finish(
                handle,
                event_sink,
                "failed",
                error_code=exc.code.value,
                message=str(exc),
                node_id=err_node,
            )
        except GraphRecursionError as exc:
            return await self._finish(
                handle,
                event_sink,
                "failed",
                error_code=RuntimeErrorCode.RT105.value,
                message=f"recursion limit reached: {exc}",
            )
        except Exception as exc:
            # catch-all (SPEC §5.6): an unexpected crash must still produce a
            # failed run row, a run_finished event and a closed stream — never a
            # zombie 'running' run whose SSE subscribers heartbeat forever
            logger.exception("run %s crashed", run_id)
            return await self._finish(
                handle,
                event_sink,
                "failed",
                error_code=RuntimeErrorCode.RT103.value,
                message=f"internal error: {exc}",
                node_id=last_started_node or None,
            )

    async def _resolve_graph_input(
        self,
        compiled: CompiledFlow,
        handle: RunHandle,
        sink: EventSink | None,
        *,
        input_text: str,
        data: dict[str, Any] | None,
        files: list[dict[str, Any]] | None,
        messages: list[Any] | None,
        resume: Any,
        debug: bool,
        debug_action: str | None,
    ) -> tuple[Any, bool]:
        """Graph input + effective debug flag, plus the matching start event (§6.1).

        ``debug_action`` overrides ``debug``: "step" keeps pausing before every
        node, "continue" finishes the paused debug run without further pauses.
        """
        run_id, thread_id = handle.run_id, handle.thread_id
        if debug_action in ("step", "continue"):
            await self._emit(sink, run_id, thread_id, "run_resumed", {"debug_action": debug_action})
            # None graph input: proceed from the debug pause point
            return None, debug_action == "step"
        if resume is not None:
            await self._emit(sink, run_id, thread_id, "run_resumed", {})
            return Command(resume=resume), debug
        await self._emit(
            sink,
            run_id,
            thread_id,
            "run_started",
            {"flow": compiled.spec.flow.slug, "mode": handle.mode, "debug": debug},
        )
        graph_input = initial_state(
            run_id=run_id,
            thread_id=thread_id,
            mode=handle.mode,
            input_text=input_text,
            data=data,
            files=files,
            messages=messages,
        )
        return graph_input, debug

    async def _finish(
        self,
        handle: RunHandle,
        sink: EventSink | None,
        status: str,
        *,
        error_code: str | None = None,
        message: str | None = None,
        node_id: str | None = None,
        text: str = "",
        structured: Any = None,
    ) -> RunResult:
        """Shared terminal sequence: status row FIRST, then the terminal event,
        then close the bus stream. SSE consumers re-read the run row when the
        stream ends and must see the terminal state (no race)."""
        run_id, thread_id = handle.run_id, handle.thread_id
        preview = text[: self._preview_length]
        status_kw: dict[str, Any] = {}
        if error_code is not None:
            status_kw["error_code"] = error_code
        if message is not None:
            status_kw["error_message"] = message
        if node_id is not None:
            status_kw["node_id"] = node_id
        if status == "completed":
            status_kw["result_preview"] = preview
        await self._status(run_id, status, **status_kw)
        if status == "cancelled":
            await self._emit(sink, run_id, thread_id, "run_cancelled", {})
        else:
            data: dict[str, Any] = {"status": status}
            if status == "completed":
                data["result_preview"] = preview
            if error_code is not None:
                data["error_code"] = error_code
            if message is not None:
                data["message"] = message
            if node_id is not None:
                data["node_id"] = node_id
            await self._emit(sink, run_id, thread_id, "run_finished", data)
        if self._bus is not None:
            self._bus.close_run(run_id)
        return RunResult(
            run_id=run_id,
            thread_id=thread_id,
            status=status,
            result_text=text,
            result_json=structured,
            error_code=error_code,
            error_message=message,
            node_id=node_id,
        )

    @staticmethod
    def _check_data_conflicts(writers: dict[str, str], node_id: str, delta: dict[str, Any]) -> None:
        """RT101: two nodes writing the same data key in one superstep (§5.1/§5.6).

        ``writers`` accumulates ``key → node`` for the current superstep; the
        caller resets it when the step number changes.
        """
        for key in (delta.get("data") or {}).keys():
            other = writers.get(key)
            if other is not None and other != node_id:
                raise RuntimeError_(
                    RuntimeErrorCode.RT101,
                    f"concurrent writes to data[{key!r}] by {other!r} and {node_id!r}",
                    node_id=node_id,
                )
            writers[key] = node_id

    # ---------------------------------------------------------------- control
    def start(self, compiled: CompiledFlow, **kwargs: Any) -> RunHandle:
        """Fire-and-forget run as an asyncio task; handle is registered."""
        run_id = kwargs.pop("run_id", None) or str(ULID()).lower()
        thread_id = kwargs.pop("thread_id", None) or str(ULID()).lower()
        mode = kwargs.get("mode", "api")
        handle = RunHandle(
            run_id=run_id,
            thread_id=thread_id,
            flow_slug=compiled.spec.flow.slug,
            mode=mode,
            run_context=RunContext(run_id=run_id, thread_id=thread_id, mode=mode),
        )
        self.runs[run_id] = handle

        async def _runner() -> None:
            try:
                await self.execute(compiled, handle=handle, register=False, **kwargs)
            except Exception:
                logger.exception("background run %s crashed", run_id)
            finally:
                handle.done.set()
                self.runs.pop(run_id, None)

        handle.task = asyncio.get_running_loop().create_task(_runner())
        return handle

    async def cancel(self, run_id: str) -> bool:
        """Request cancellation; does NOT await the run's death.

        Awaiting here can deadlock the A2A cancel path: the dying producer
        blocks on draining its event queue, which only the caller's consumer
        (running after this returns) will drain.
        """
        handle = self.runs.get(run_id)
        if handle is None:
            return False
        handle.run_context.cancellation.set()
        if handle.task is not None and not handle.task.done():
            handle.task.cancel()
        return True


# ------------------------------------------------------------------ headless API (§2.7)
async def run_compiled_once(
    compiled: CompiledFlow, *, input_text: str = "hi", data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One in-memory run, no persistence — powers the test harness and --local."""
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    executor = Executor(checkpointer_getter=lambda: _coro(saver))
    result = await executor.execute(compiled, input_text=input_text, data=data, mode="api")
    return {
        "status": result.status,
        "result_text": result.result_text,
        "result_json": result.result_json,
        "interrupt": result.interrupt,
        "run_id": result.run_id,
        "thread_id": result.thread_id,
    }


async def _coro(value: Any) -> Any:
    return value


async def arun_flow(
    source: Any,
    *,
    input_text: str = "",
    data: dict[str, Any] | None = None,
    session_id: str | None = None,
    resume: Any = None,
    checkpointer: Any = None,
    registry: Any = None,
    tweaks: dict[str, dict[str, Any]] | None = None,
) -> RunResult:
    """Headless execution of a FlowSpec (SPEC §2.7)."""
    from langgraph_agent_builder.compiler import compile_flow

    compiled = (
        source
        if isinstance(source, CompiledFlow)
        else compile_flow(source, registry=registry, tweaks=tweaks)
    )
    if not compiled.ok:
        errors = [d for d in compiled.diagnostics if d.severity == "error"]
        raise ValueError(
            "flow has compile errors: " + "; ".join(f"{d.code}: {d.message}" for d in errors)
        )
    if checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = InMemorySaver()
    executor = Executor(checkpointer_getter=lambda: _coro(checkpointer))
    return await executor.execute(
        compiled,
        thread_id=session_id,
        input_text=input_text,
        data=data,
        resume=resume,
        mode="api",
    )


def run_flow(source: Any, **kwargs: Any) -> RunResult:
    """Sync wrapper around arun_flow."""
    return asyncio.run(arun_flow(source, **kwargs))
