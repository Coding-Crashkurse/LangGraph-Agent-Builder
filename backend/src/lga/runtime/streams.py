"""Event bus: in-proc pub/sub + persistence to run_events (SPEC §6.2).

Single-process by design; the fan-out lives behind this interface so a
LISTEN/NOTIFY implementation can replace it without touching callers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable

from lga.schema.events import RunEvent
from lga.schema.scrub import scrub_data

logger = logging.getLogger("lga.events")

PersistFn = Callable[[RunEvent], Awaitable[None]]
LoadFn = Callable[[str, int], Awaitable[list[RunEvent]]]


class EventBus:
    def __init__(
        self,
        persist: PersistFn | None = None,
        load: LoadFn | None = None,
        buffer_size: int = 512,
    ) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[RunEvent | None]]] = defaultdict(set)
        self._firehose: set[asyncio.Queue[RunEvent | None]] = set()
        self._seq: dict[str, int] = {}
        self._persist = persist
        self._load = load
        self._buffer_size = buffer_size
        self._persist_queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        self._persist_task: asyncio.Task[None] | None = None

    # ---------------------------------------------------------------- publish
    def publish(self, event: RunEvent) -> RunEvent:
        # scrub secrets before anything sees the event — SSE subscribers AND the
        # persisted row are both fed from this one object (SPEC §10.5)
        event.data = scrub_data(event.data)
        seq = self._seq.get(event.run_id, 0) + 1
        self._seq[event.run_id] = seq
        event.seq = seq
        for queue in list(self._subscribers.get(event.run_id, ())) + list(self._firehose):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)
        if self._persist is not None:
            self._ensure_persist_task()
            self._persist_queue.put_nowait(event)
        return event

    def set_seq_floor(self, run_id: str, seq: int) -> None:
        """After restart: continue numbering above what's persisted."""
        self._seq[run_id] = max(self._seq.get(run_id, 0), seq)

    def close_run(self, run_id: str) -> None:
        """Signal end-of-stream to live subscribers of a finished run."""
        for queue in list(self._subscribers.get(run_id, ())):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)
        self._seq.pop(run_id, None)

    # ---------------------------------------------------------------- subscribe
    async def subscribe(
        self, run_id: str, after_seq: int = 0, replay: bool = True
    ) -> AsyncIterator[RunEvent]:
        """Replay persisted events first (Last-Event-ID), then live tail."""
        queue: asyncio.Queue[RunEvent | None] = asyncio.Queue(self._buffer_size)
        self._subscribers[run_id].add(queue)
        try:
            last = after_seq
            event: RunEvent | None
            if replay and self._load is not None:
                for event in await self._load(run_id, after_seq):
                    last = max(last, event.seq)
                    yield event
            while True:
                event = await queue.get()
                if event is None:
                    return
                if event.seq <= last:
                    continue  # already replayed
                last = event.seq
                yield event
                if event.event in ("run_finished", "run_cancelled"):
                    return
        finally:
            self._subscribers[run_id].discard(queue)
            if not self._subscribers[run_id]:
                del self._subscribers[run_id]

    async def subscribe_firehose(self) -> AsyncIterator[RunEvent]:
        queue: asyncio.Queue[RunEvent | None] = asyncio.Queue(self._buffer_size)
        self._firehose.add(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield event
        finally:
            self._firehose.discard(queue)

    # ---------------------------------------------------------------- persistence
    def _ensure_persist_task(self) -> None:
        if self._persist_task is None or self._persist_task.done():
            self._persist_task = asyncio.get_running_loop().create_task(self._persist_loop())

    async def _persist_loop(self) -> None:
        assert self._persist is not None
        while True:
            event = await self._persist_queue.get()
            try:
                await self._persist(event)
            except Exception:  # persistence must never kill the run
                logger.exception("failed to persist run event %s/%s", event.run_id, event.seq)
            finally:
                self._persist_queue.task_done()

    async def drain(self) -> None:
        """Flush pending persistence (used by tests and graceful shutdown)."""
        if self._persist_task is not None and not self._persist_task.done():
            await self._persist_queue.join()
