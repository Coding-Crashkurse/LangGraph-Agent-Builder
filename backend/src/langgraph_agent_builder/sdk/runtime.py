"""RunContext — what a NodeFn can reach at runtime (SPEC §4.1).

Nodes obtain it via ``get_run_context(config)``. When the compiled graph runs
under vanilla LangGraph (no lab runtime), a no-op context is returned so
components degrade gracefully (custom events become no-ops).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("langgraph_agent_builder.runtime")

RUN_CTX_KEY = "__lga_run_ctx__"

# Set by the compiler's node wrapper around each node execution so events carry
# node attribution without threading node_id through every emit call.
current_node_id: ContextVar[str] = ContextVar("lga_current_node_id", default="")


def stream_write(payload: dict[str, Any]) -> None:
    """Best-effort write to langgraph's custom stream; no-op outside a stream."""
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        return
    if writer is None:
        return
    try:
        writer(payload)
    except Exception:  # pragma: no cover - defensive
        logger.debug("stream write failed", exc_info=True)


# Back-compat alias from when the compiler reached for the private name.
_stream_write = stream_write


@dataclass
class RunContext:
    run_id: str = ""
    thread_id: str = ""
    attempt: int = 1
    cancellation: asyncio.Event = field(default_factory=asyncio.Event)
    mode: str = "api"
    _noop: bool = False
    # Opaque, DB-free sink for the per-node run timeline (REFACTOR.md §7). The
    # compiler node wrapper calls it with a plain payload dict; the executor/app
    # layer wires it to a background writer in RunService (keeps sdk/compiler
    # DB-clean — mirrors how ``on_status`` is wired). None ⇒ nothing recorded.
    record_node_run: Callable[[dict[str, Any]], None] | None = None
    # Per-(run, node) iteration counter — iterations are not on events, so the
    # wrapper increments this on each ``node_started`` (looped/resumed nodes
    # produce distinct rows). Per RunContext ⇒ per execute() call.
    _node_iterations: dict[str, int] = field(default_factory=dict)

    # ---------------------------------------------------------------- iterations
    def next_iteration(self, node_id: str) -> int:
        """Increment and return this node's iteration for the current run."""
        nxt = self._node_iterations.get(node_id, 0) + 1
        self._node_iterations[node_id] = nxt
        return nxt

    def current_iteration(self, node_id: str) -> int:
        """This node's current iteration without advancing it (≥1 once started)."""
        return self._node_iterations.get(node_id, 1)

    # ---------------------------------------------------------------- emitters
    def emit_status(self, text: str) -> None:
        """Node status line in the UI (throttle-friendly, human-readable)."""
        self._emit("node_status", {"text": text})

    def emit_log(self, level: str, msg: str) -> None:
        self._emit("node_log", {"level": level, "msg": msg})

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Free-form custom event; forwarded to SSE + A2A working updates."""
        self._emit(event_type, data)

    def stream_writer(self, delta: str) -> None:
        """Token streaming into the assistant bubble / A2A artifact chunks."""
        self._emit("node_token", {"delta": delta})

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._noop:
            return
        stream_write(
            {
                "event": event_type,
                "node_id": current_node_id.get(),
                "data": data,
            }
        )

    # ---------------------------------------------------------------- cancel
    @property
    def cancelled(self) -> bool:
        return self.cancellation.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancellation.is_set():
            raise asyncio.CancelledError("run cancelled")


_NOOP = RunContext(_noop=True)


def get_run_context(config: dict[str, Any] | Any) -> RunContext:
    """Fetch the RunContext from a LangGraph RunnableConfig."""
    try:
        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        ctx = configurable.get(RUN_CTX_KEY)
    except Exception:  # pragma: no cover - defensive
        ctx = None
    return ctx if isinstance(ctx, RunContext) else _NOOP


# Back-compat alias used in SPEC §2.7 exports
NodeContext = RunContext
