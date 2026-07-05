"""EventBus (in-proc pub/sub + persistence to task_events) and the component
`emit()` helper. See CLAUDE.md §12 for the event envelope."""

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal

from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

logger = logging.getLogger(__name__)

EventSource = Literal["a2a", "mcp", "system"]

# Set by the compiler around every node call so custom events carry their node id.
current_node: ContextVar[str | None] = ContextVar("graphforge_current_node", default=None)


class TaskEvent(BaseModel):
    """Our debug/streaming event envelope (not an A2A/MCP protocol type)."""

    id: str = Field(default_factory=lambda: str(ULID()))
    task_id: str
    flow_id: str
    source: EventSource = "system"
    type: str
    node: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


def emit(event_type: str, data: dict[str, Any] | None = None) -> None:
    """Emit a custom progress event from inside a component node function.

    Safe no-op when the graph is not running or the caller is outside a run
    context (CLAUDE.md §18: custom events must degrade gracefully).
    """
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    if writer is None:
        return
    writer({"type": event_type, "data": data or {}, "node": current_node.get()})


class EventBus:
    """In-process pub/sub keyed by task id and flow id (firehose).

    Every published event is also appended to `task_events` via a
    fire-and-forget queue (when `start()` was called with a sessionmaker).
    Single-process by design; swap fan-out for LISTEN/NOTIFY behind this
    interface if we ever scale out. No Redis (CLAUDE.md §12).
    """

    def __init__(self) -> None:
        self._task_subs: defaultdict[str, set[asyncio.Queue[TaskEvent]]] = defaultdict(set)
        self._flow_subs: defaultdict[str, set[asyncio.Queue[TaskEvent]]] = defaultdict(set)
        self._persist_queue: asyncio.Queue[TaskEvent] | None = None
        self._persist_task: asyncio.Task[None] | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    # -- publishing ---------------------------------------------------------

    def publish(self, event: TaskEvent) -> None:
        for queue in self._task_subs.get(event.task_id, ()):
            queue.put_nowait(event)
        for queue in self._flow_subs.get(event.flow_id, ()):
            queue.put_nowait(event)
        if self._persist_queue is not None:
            self._persist_queue.put_nowait(event)

    def publish_event(
        self,
        *,
        task_id: str,
        flow_id: str,
        source: EventSource,
        type: str,
        node: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> TaskEvent:
        event = TaskEvent(
            task_id=task_id,
            flow_id=flow_id,
            source=source,
            type=type,
            node=node,
            data=data or {},
        )
        self.publish(event)
        return event

    # -- subscriptions ------------------------------------------------------

    @asynccontextmanager
    async def subscribe_task(self, task_id: str) -> AsyncIterator[asyncio.Queue[TaskEvent]]:
        queue: asyncio.Queue[TaskEvent] = asyncio.Queue()
        self._task_subs[task_id].add(queue)
        try:
            yield queue
        finally:
            self._task_subs[task_id].discard(queue)
            if not self._task_subs[task_id]:
                self._task_subs.pop(task_id, None)

    @asynccontextmanager
    async def subscribe_flow(self, flow_id: str) -> AsyncIterator[asyncio.Queue[TaskEvent]]:
        queue: asyncio.Queue[TaskEvent] = asyncio.Queue()
        self._flow_subs[flow_id].add(queue)
        try:
            yield queue
        finally:
            self._flow_subs[flow_id].discard(queue)
            if not self._flow_subs[flow_id]:
                self._flow_subs.pop(flow_id, None)

    # -- persistence --------------------------------------------------------

    async def start(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._persist_queue = asyncio.Queue()
        self._persist_task = asyncio.create_task(self._persist_loop(), name="event-bus-persist")

    async def stop(self) -> None:
        if self._persist_task is not None:
            self._persist_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._persist_task
            self._persist_task = None
        self._persist_queue = None
        self._sessionmaker = None

    async def _persist_loop(self) -> None:
        from graphforge.db.models import TaskEventRow

        assert self._persist_queue is not None
        assert self._sessionmaker is not None
        while True:
            event = await self._persist_queue.get()
            batch = [event]
            while not self._persist_queue.empty() and len(batch) < 100:
                batch.append(self._persist_queue.get_nowait())
            try:
                async with self._sessionmaker() as session:
                    session.add_all(
                        TaskEventRow(
                            id=ev.id,
                            task_id=ev.task_id,
                            flow_id=ev.flow_id,
                            source=ev.source,
                            type=ev.type,
                            node=ev.node,
                            payload=ev.data,
                            created_at=ev.ts,
                        )
                        for ev in batch
                    )
                    await session.commit()
            except Exception:  # persistence must never take the bus down
                logger.exception("failed to persist %d task event(s)", len(batch))
