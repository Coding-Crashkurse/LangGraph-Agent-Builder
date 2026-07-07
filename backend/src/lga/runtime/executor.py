"""Run orchestration: execute/resume/cancel/debug (SPEC §6.1).

All run modes (playground/api/debug/a2a/mcp) share this executor.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from pydantic import BaseModel
from ulid import ULID

from lga.compiler import CompiledFlow
from lga.schema.diagnostics import RuntimeError_, RuntimeErrorCode
from lga.schema.events import RunEvent
from lga.schema.state import initial_state
from lga.sdk.component import NodeKind
from lga.sdk.ports import Message
from lga.sdk.runtime import RUN_CTX_KEY, RunContext
from lga.sdk.templating import message_text

logger = logging.getLogger("lga.executor")

RUN_STATUSES = (
    "pending",
    "running",
    "input_required",
    "completed",
    "failed",
    "cancelled",
)

StatusHook = Callable[..., Awaitable[None]]


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


@dataclass
class RunHandle:
    run_id: str
    thread_id: str
    flow_slug: str
    mode: str
    run_context: RunContext
    task: asyncio.Task | None = None
    result: RunResult | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)


def extract_result(compiled: CompiledFlow, state_values: dict[str, Any]) -> tuple[str, Any]:
    """Terminal node result → (text, structured|None) (SPEC §7.8 outbound)."""
    ports_map = state_values.get("ports") or {}
    assert compiled.ir is not None
    for node in compiled.ir.nodes.values():
        if node.kind != NodeKind.TERMINAL:
            continue
        for out_name in node.outputs:
            value = ports_map.get(f"{node.id}.{out_name}")
            if value is None:
                continue
            if isinstance(value, Message):
                return value.content, None
            if isinstance(value, str):
                return value, None
            if isinstance(value, dict):
                import json

                return json.dumps(value, ensure_ascii=False, default=str), value
            return str(value), None
    # fallback: last assistant message
    msgs = [m for m in state_values.get("messages") or [] if getattr(m, "type", "") == "ai"]
    return (message_text(msgs[-1]) if msgs else ""), None


class Executor:
    def __init__(
        self,
        *,
        checkpointer_getter: Callable[[], Awaitable[Any]],
        bus: Any = None,  # EventBus | None
        on_status: StatusHook | None = None,
        recursion_limit_default: int = 50,
        preview_length: int = 300,  # LGA_MAX_TEXT_LENGTH
    ) -> None:
        self._get_checkpointer = checkpointer_getter
        self._bus = bus
        self._on_status = on_status
        self._recursion_default = recursion_limit_default
        self._preview_length = preview_length
        self.runs: dict[str, RunHandle] = {}

    # ---------------------------------------------------------------- events
    def _publish(self, run_id: str, thread_id: str, event: str, data: dict[str, Any]) -> None:
        if self._bus is not None:
            self._bus.publish(RunEvent(event=event, run_id=run_id, thread_id=thread_id, data=data))

    async def _emit(
        self,
        sink: Callable[[RunEvent], Awaitable[None]] | None,
        run_id: str,
        thread_id: str,
        event: str,
        data: dict[str, Any],
    ) -> None:
        self._publish(run_id, thread_id, event, data)
        if sink is not None:
            try:
                await sink(RunEvent(event=event, run_id=run_id, thread_id=thread_id, data=data))
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
        register: bool = True,
        run_context: RunContext | None = None,
        event_sink: Callable[[RunEvent], Awaitable[None]] | None = None,
    ) -> RunResult:
        """Run to completion or interrupt. Returns the RunResult either way."""
        run_id = run_id or str(ULID()).lower()
        thread_id = thread_id or str(ULID()).lower()
        rc = run_context or RunContext(run_id=run_id, thread_id=thread_id, mode=mode)
        handle = RunHandle(
            run_id=run_id,
            thread_id=thread_id,
            flow_slug=compiled.spec.flow.slug,
            mode=mode,
            run_context=rc,
            task=asyncio.current_task(),
        )
        if register:
            self.runs[run_id] = handle
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
                event_sink=event_sink,
            )
        except asyncio.CancelledError:
            result = RunResult(
                run_id=run_id,
                thread_id=thread_id,
                status="cancelled",
                error_code=RuntimeErrorCode.RT104.value,
                error_message="run cancelled",
            )
            self._publish(run_id, thread_id, "run_cancelled", {})
            await self._status(run_id, "cancelled", error_code=result.error_code)
            if self._bus is not None:
                self._bus.close_run(run_id)
            # swallow only if cancellation was requested through cancel();
            # otherwise propagate so callers see the cancellation
            if not rc.cancellation.is_set():
                handle.result = result
                handle.done.set()
                raise
        finally:
            handle.result = handle.result or None
            if register:
                self.runs.pop(run_id, None)
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
        event_sink: Callable[[RunEvent], Awaitable[None]] | None = None,
    ) -> RunResult:
        run_id, thread_id = handle.run_id, handle.thread_id
        checkpointer = await self._get_checkpointer()
        graph = compiled.compile(checkpointer=checkpointer)
        config: dict[str, Any] = {
            "configurable": {"thread_id": thread_id, RUN_CTX_KEY: handle.run_context},
            "recursion_limit": compiled.spec.flow.settings.recursion_limit
            or self._recursion_default,
        }
        stream_kwargs: dict[str, Any] = {}
        if debug or debug_action == "step":
            stream_kwargs["interrupt_before"] = "*"
        if debug_action == "continue":
            debug = False

        if debug_action in ("step", "continue"):
            graph_input: Any = None  # proceed from the debug pause point
            debug = debug or debug_action == "step"
            await self._emit(
                event_sink, run_id, thread_id, "run_resumed", {"debug_action": debug_action}
            )
        elif resume is not None:
            graph_input = Command(resume=resume)
            await self._emit(event_sink, run_id, thread_id, "run_resumed", {})
        else:
            graph_input = initial_state(
                run_id=run_id,
                thread_id=thread_id,
                mode=handle.mode,
                input_text=input_text,
                data=data,
                files=files,
                messages=messages,
            )
            await self._emit(
                event_sink,
                run_id,
                thread_id,
                "run_started",
                {"flow": compiled.spec.flow.slug, "mode": handle.mode, "debug": debug},
            )
        await self._status(run_id, "running")

        interrupt_payload: dict[str, Any] | None = None
        interrupt_node: str | None = None
        last_started_node = ""
        try:
            async for stream_mode, chunk in graph.astream(
                graph_input, config, stream_mode=["custom", "updates"], **stream_kwargs
            ):
                if stream_mode == "custom" and isinstance(chunk, dict):
                    event = str(chunk.get("event") or "custom")
                    node_id = str(chunk.get("node_id") or "")
                    if event == "node_started":
                        last_started_node = node_id
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
                        raw = interrupts[0].value if interrupts else {}
                        interrupt_payload = raw if isinstance(raw, dict) else {"value": raw}
                        interrupt_node = last_started_node or None
                        # do NOT break: closing the generator early can cancel
                        # langgraph's async checkpoint flush — on Postgres the
                        # interrupt would then be missing when the resume
                        # request inspects the thread state
                        continue
                    self._check_data_conflicts(chunk)
        except RuntimeError_ as exc:
            # status BEFORE the event: SSE consumers re-read the run row on
            # run_finished and must see the terminal state (no race)
            await self._status(run_id, "failed", error_code=exc.code.value, error_message=str(exc))
            await self._emit(
                event_sink,
                run_id,
                thread_id,
                "run_finished",
                {"status": "failed", "error_code": exc.code.value, "message": str(exc)},
            )
            if self._bus is not None:
                self._bus.close_run(run_id)
            return RunResult(
                run_id=run_id,
                thread_id=thread_id,
                status="failed",
                error_code=exc.code.value,
                error_message=str(exc),
            )
        except GraphRecursionError as exc:
            code = RuntimeErrorCode.RT105.value
            await self._status(run_id, "failed", error_code=code, error_message=str(exc))
            await self._emit(
                event_sink,
                run_id,
                thread_id,
                "run_finished",
                {"status": "failed", "error_code": code, "message": str(exc)},
            )
            if self._bus is not None:
                self._bus.close_run(run_id)
            return RunResult(
                run_id=run_id,
                thread_id=thread_id,
                status="failed",
                error_code=code,
                error_message=f"recursion limit reached: {exc}",
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
        text, structured = extract_result(compiled, snapshot.values or {})
        await self._status(run_id, "completed", result_preview=text[: self._preview_length])
        await self._emit(
            event_sink,
            run_id,
            thread_id,
            "run_finished",
            {"status": "completed", "result_preview": text[: self._preview_length]},
        )
        if self._bus is not None:
            self._bus.close_run(run_id)
        return RunResult(
            run_id=run_id,
            thread_id=thread_id,
            status="completed",
            result_text=text,
            result_json=structured,
        )

    @staticmethod
    def _check_data_conflicts(chunk: dict[str, Any]) -> None:
        """RT101: two nodes writing the same data key in one superstep."""
        writers: dict[str, str] = {}
        for node_name, delta in chunk.items():
            if not isinstance(delta, dict):
                continue
            for key in (delta.get("data") or {}).keys():
                if key in writers and writers[key] != node_name:
                    raise RuntimeError_(
                        RuntimeErrorCode.RT101,
                        f"concurrent writes to data[{key!r}] by {writers[key]!r} and {node_name!r}",
                    )
                writers[key] = node_name

    # ---------------------------------------------------------------- control
    def start(self, compiled: CompiledFlow, **kwargs: Any) -> RunHandle:
        """Fire-and-forget run as an asyncio task; handle is registered."""
        run_id = kwargs.pop("run_id", None) or str(ULID()).lower()
        thread_id = kwargs.pop("thread_id", None) or str(ULID()).lower()
        rc = RunContext(run_id=run_id, thread_id=thread_id, mode=kwargs.get("mode", "api"))
        handle = RunHandle(
            run_id=run_id,
            thread_id=thread_id,
            flow_slug=compiled.spec.flow.slug,
            mode=kwargs.get("mode", "api"),
            run_context=rc,
        )
        self.runs[run_id] = handle

        async def _runner() -> None:
            try:
                result = await self.execute(
                    compiled,
                    run_id=run_id,
                    thread_id=thread_id,
                    register=False,
                    run_context=rc,
                    **kwargs,
                )
                handle.result = result
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
    from lga.compiler import compile_flow

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
