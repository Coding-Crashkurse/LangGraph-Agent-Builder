"""Run event envelope — SSE and internal bus share this shape (SPEC §6.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "run_started",
    "node_started",
    "node_token",
    "node_status",
    "node_log",
    "node_finished",
    "node_error",
    "interrupt_raised",
    "run_resumed",
    "run_finished",
    "run_cancelled",
    "heartbeat",
    "custom",
]

HEARTBEAT_INTERVAL_S = 15.0


class RunEvent(BaseModel):
    event: str  # EventType or custom.<type>
    run_id: str
    thread_id: str = ""
    seq: int = 0  # monotonic per run; assigned by the event bus
    ts: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    data: dict[str, Any] = Field(default_factory=dict)

    def sse(self) -> dict[str, Any]:
        """kwargs for sse-starlette ServerSentEvent."""
        return {
            "event": self.event,
            "id": str(self.seq),
            "data": self.model_dump_json(),
        }
