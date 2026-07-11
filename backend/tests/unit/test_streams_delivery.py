"""Event-bus delivery guarantees under overflow and shutdown (SPEC §6.2).

A full subscriber queue drops its oldest unprotected event — the consumer can
replay the seq gap via Last-Event-ID — but ``run_finished``/``run_cancelled``/
``interrupt_raised`` and the close sentinel must always land, or the SSE
stream heartbeats forever. Also covers replay ending on a persisted terminal
event and ``aclose()`` stopping the persistence task.
"""

from __future__ import annotations

import asyncio

from langgraph_agent_builder.runtime.streams import EventBus
from langgraph_agent_builder.schema.events import RunEvent


def _event(run_id: str, event: str = "node_log", **data: str) -> RunEvent:
    return RunEvent(event=event, run_id=run_id, data=dict(data))


# --------------------------------------------------------------- overflow
async def test_overflow_drops_oldest_not_newest() -> None:
    bus = EventBus(buffer_size=2)
    queue: asyncio.Queue[RunEvent | None] = asyncio.Queue(2)
    bus._subscribers["r1"].add(queue)

    bus.publish(_event("r1", msg="a"))
    bus.publish(_event("r1", msg="b"))
    bus.publish(_event("r1", msg="c"))  # overflow: "a" is sacrificed

    got = [queue.get_nowait() for _ in range(2)]
    assert [e.data["msg"] for e in got if e is not None] == ["b", "c"]


async def test_overflow_never_drops_terminal_or_interrupt_events() -> None:
    bus = EventBus(buffer_size=3)
    queue: asyncio.Queue[RunEvent | None] = asyncio.Queue(3)
    bus._subscribers["r1"].add(queue)

    bus.publish(_event("r1", "interrupt_raised"))
    bus.publish(_event("r1", "node_log", msg="x"))
    bus.publish(_event("r1", "run_finished"))
    bus.publish(_event("r1", "node_log", msg="late"))  # evicts "x", keeps protected

    got = [queue.get_nowait() for _ in range(3)]
    assert [e.event for e in got if e is not None] == [
        "interrupt_raised",
        "run_finished",
        "node_log",
    ]


async def test_overflow_drops_new_unprotected_event_when_queue_all_protected() -> None:
    bus = EventBus(buffer_size=1)
    queue: asyncio.Queue[RunEvent | None] = asyncio.Queue(1)
    bus._subscribers["r1"].add(queue)

    bus.publish(_event("r1", "run_finished"))
    bus.publish(_event("r1", "node_log", msg="late"))  # nothing droppable but itself

    assert queue.qsize() == 1
    only = queue.get_nowait()
    assert only is not None
    assert only.event == "run_finished"


async def test_close_sentinel_lands_on_full_queue() -> None:
    bus = EventBus(buffer_size=1)
    queue: asyncio.Queue[RunEvent | None] = asyncio.Queue(1)
    bus._subscribers["r1"].add(queue)
    bus.publish(_event("r1", msg="stale"))

    bus.close_run("r1")  # sentinel evicts the stale event instead of vanishing
    assert queue.get_nowait() is None


async def test_slow_subscriber_still_sees_run_finished() -> None:
    bus = EventBus(buffer_size=2)
    got: list[RunEvent] = []

    async def collect() -> None:
        async for event in bus.subscribe("r1", replay=False):
            got.append(event)

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)  # let the subscriber register, then outrun it
    for i in range(10):
        bus.publish(_event("r1", msg=str(i)))
    bus.publish(_event("r1", "run_finished"))
    await asyncio.wait_for(task, timeout=2)

    assert got  # some tail survived the overflow
    assert got[-1].event == "run_finished"  # and the generator terminated


# --------------------------------------------------------------- replay
async def test_replay_of_finished_run_ends_without_live_tail() -> None:
    persisted = [
        RunEvent(event="run_started", run_id="r1", seq=1),
        RunEvent(event="run_finished", run_id="r1", seq=2),
    ]

    async def load(run_id: str, after_seq: int) -> list[RunEvent]:
        return [e for e in persisted if e.seq > after_seq]

    bus = EventBus(load=load)

    async def collect() -> list[RunEvent]:
        return [e async for e in bus.subscribe("r1", replay=True)]

    got = await asyncio.wait_for(collect(), timeout=2)
    assert [e.event for e in got] == ["run_started", "run_finished"]


# --------------------------------------------------------------- shutdown
async def test_aclose_flushes_then_stops_persist_task() -> None:
    stored: list[RunEvent] = []

    async def persist(event: RunEvent) -> None:
        stored.append(event)

    bus = EventBus(persist=persist)
    bus.publish(_event("r1", msg="a"))
    task = bus._persist_task
    assert task is not None

    await bus.aclose()
    assert [e.data["msg"] for e in stored] == ["a"]  # flushed before cancel
    assert task.done()
    assert bus._persist_task is None
