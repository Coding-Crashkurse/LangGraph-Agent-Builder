"""Event bus fan-out and persistence — SPEC §6.2.

Covers ``lga.runtime.streams.EventBus``: monotonic per-run sequencing, live
subscriber delivery + ordering, replay-then-tail with de-duplication,
end-of-stream signalling (terminal events, ``close_run``), the firehose,
backpressure drops on a full subscriber queue, the seq floor, and the
background persistence loop (including a failing persist that must not kill
the run).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from lga.runtime.streams import EventBus
from lga.schema.events import RunEvent

if TYPE_CHECKING:
    from collections.abc import Awaitable


def _event(run_id: str, event: str = "node_log", **data: str) -> RunEvent:
    return RunEvent(event=event, run_id=run_id, data=dict(data))


async def _collect(
    bus: EventBus, run_id: str, sink: list[RunEvent], *, replay: bool = True
) -> None:
    async for event in bus.subscribe(run_id, replay=replay):
        sink.append(event)


# --------------------------------------------------------------- sequencing
async def test_publish_assigns_monotonic_seq_per_run() -> None:
    bus = EventBus()
    seqs = [bus.publish(_event("r1")).seq for _ in range(3)]
    assert seqs == [1, 2, 3]


async def test_publish_sequences_runs_independently() -> None:
    bus = EventBus()
    assert bus.publish(_event("a")).seq == 1
    assert bus.publish(_event("b")).seq == 1
    assert bus.publish(_event("a")).seq == 2


async def test_set_seq_floor_continues_numbering_above_persisted() -> None:
    bus = EventBus()
    bus.set_seq_floor("r1", 7)
    assert bus.publish(_event("r1")).seq == 8
    # floor never lowers an already-higher counter
    bus.set_seq_floor("r1", 2)
    assert bus.publish(_event("r1")).seq == 9


# --------------------------------------------------------------- live delivery
async def test_subscriber_receives_live_events_in_order() -> None:
    bus = EventBus()
    got: list[RunEvent] = []
    task = asyncio.create_task(_collect(bus, "r1", got, replay=False))
    await asyncio.sleep(0)  # let the subscriber register its queue

    bus.publish(_event("r1", msg="one"))
    bus.publish(_event("r1", msg="two"))
    bus.close_run("r1")
    await asyncio.wait_for(task, timeout=2)

    assert [e.data["msg"] for e in got] == ["one", "two"]
    # close_run cleared the run's sequence counter
    assert "r1" not in bus._seq


async def test_terminal_event_ends_subscription() -> None:
    bus = EventBus()
    got: list[RunEvent] = []
    task = asyncio.create_task(_collect(bus, "r1", got, replay=False))
    await asyncio.sleep(0)

    bus.publish(_event("r1", "node_log"))
    bus.publish(_event("r1", "run_finished"))
    # generator must return on the terminal event without a close_run() call
    await asyncio.wait_for(task, timeout=2)
    assert [e.event for e in got] == ["node_log", "run_finished"]


async def test_unsubscribe_removes_queue_on_exit() -> None:
    bus = EventBus()
    got: list[RunEvent] = []
    task = asyncio.create_task(_collect(bus, "r1", got, replay=False))
    await asyncio.sleep(0)
    assert bus._subscribers["r1"]  # registered while iterating

    bus.close_run("r1")
    await asyncio.wait_for(task, timeout=2)
    # finally-block deleted the now-empty subscriber set
    assert "r1" not in bus._subscribers


# --------------------------------------------------------------- replay + dedup
async def test_replay_persisted_then_live_with_dedup() -> None:
    persisted = [
        RunEvent(event="run_started", run_id="r1", seq=1),
        RunEvent(event="node_log", run_id="r1", seq=2),
    ]

    async def load(run_id: str, after_seq: int) -> list[RunEvent]:
        return [e for e in persisted if e.run_id == run_id and e.seq > after_seq]

    bus = EventBus(load=load)
    got: list[RunEvent] = []
    task = asyncio.create_task(_collect(bus, "r1", got, replay=True))
    await asyncio.sleep(0)  # runs replay, then blocks on the live queue

    # These live events reuse seqs 1 and 2 (they were persisted before the
    # subscriber attached) and must be dropped as already-replayed; seq 3 is new.
    bus.publish(_event("r1", "node_log"))  # -> seq 1, duplicate
    bus.publish(_event("r1", "node_log"))  # -> seq 2, duplicate
    bus.publish(_event("r1", "run_finished"))  # -> seq 3, new + terminal
    await asyncio.wait_for(task, timeout=2)

    assert [e.seq for e in got] == [1, 2, 3]
    assert [e.event for e in got] == ["run_started", "node_log", "run_finished"]


async def test_replay_disabled_skips_loader() -> None:
    calls: list[str] = []

    async def load(run_id: str, after_seq: int) -> list[RunEvent]:
        calls.append(run_id)
        return []

    bus = EventBus(load=load)
    got: list[RunEvent] = []
    task = asyncio.create_task(_collect(bus, "r1", got, replay=False))
    await asyncio.sleep(0)
    bus.publish(_event("r1", "run_finished"))
    await asyncio.wait_for(task, timeout=2)
    assert calls == []  # loader untouched when replay=False


# --------------------------------------------------------------- firehose
async def test_firehose_sees_events_across_runs() -> None:
    bus = EventBus()
    got: list[RunEvent] = []

    async def drain() -> None:
        async for event in bus.subscribe_firehose():
            got.append(event)

    task = asyncio.create_task(drain())
    await asyncio.sleep(0)

    bus.publish(_event("a", msg="x"))
    bus.publish(_event("b", msg="y"))
    await asyncio.sleep(0)
    # None terminates the firehose generator (finally removes the queue)
    for queue in list(bus._firehose):
        queue.put_nowait(None)
    await asyncio.wait_for(task, timeout=2)

    assert [e.run_id for e in got] == ["a", "b"]
    assert not bus._firehose


# --------------------------------------------------------------- backpressure
async def test_full_subscriber_queue_drops_without_raising() -> None:
    bus = EventBus(buffer_size=1)
    slow: asyncio.Queue[RunEvent | None] = asyncio.Queue(1)
    slow.put_nowait(_event("r1", msg="stale"))  # queue now at capacity
    bus._subscribers["r1"].add(slow)

    published = bus.publish(_event("r1", msg="fresh"))
    # publish returns normally; the overflow event was silently dropped.
    assert published.seq == 1
    assert slow.qsize() == 1
    remaining = slow.get_nowait()
    assert remaining is not None
    assert remaining.data["msg"] == "stale"


async def test_close_run_on_full_queue_suppresses_queuefull() -> None:
    bus = EventBus(buffer_size=1)
    slow: asyncio.Queue[RunEvent | None] = asyncio.Queue(1)
    slow.put_nowait(_event("r1"))
    bus._subscribers["r1"].add(slow)
    bus.set_seq_floor("r1", 5)

    bus.close_run("r1")  # sentinel would overflow → suppressed, no raise
    assert "r1" not in bus._seq


# --------------------------------------------------------------- persistence
async def test_persist_loop_writes_published_events_and_drain_flushes() -> None:
    stored: list[RunEvent] = []

    async def persist(event: RunEvent) -> None:
        stored.append(event)

    bus = EventBus(persist=persist)
    bus.publish(_event("r1", msg="a"))
    bus.publish(_event("r1", msg="b"))
    await bus.drain()

    assert [e.data["msg"] for e in stored] == ["a", "b"]


async def test_failing_persist_is_swallowed_and_loop_survives() -> None:
    stored: list[RunEvent] = []

    async def persist(event: RunEvent) -> None:
        if event.data.get("boom"):
            raise RuntimeError("db down")
        stored.append(event)

    bus = EventBus(persist=persist)
    bus.publish(_event("r1", boom="yes"))  # raises inside loop -> logged, not fatal
    bus.publish(_event("r1", msg="after"))
    await bus.drain()

    # the run survived the persistence failure; the next event still landed
    assert [e.data.get("msg") for e in stored] == ["after"]


async def test_drain_is_noop_without_persistence() -> None:
    bus = EventBus()  # no persist fn -> no background task
    bus.publish(_event("r1"))
    awaitable: Awaitable[None] = bus.drain()
    await awaitable  # returns immediately, nothing to flush
    assert bus._persist_task is None
