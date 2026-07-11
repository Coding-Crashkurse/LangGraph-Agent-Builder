"""SSE run-stream behaviour: client-disconnect cancellation (SPEC §6.1)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from lga.api.runs import _run_event_gen
from lga.runtime.streams import EventBus
from lga.schema.events import RunEvent


class _RecordingExecutor:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def cancel(self, run_id: str) -> bool:
        self.cancelled.append(run_id)
        return True


def _svc(bus: EventBus, executor: _RecordingExecutor) -> Any:
    return SimpleNamespace(bus=bus, executor=executor)


async def _start(gen: Any) -> asyncio.Task[Any]:
    """Kick the generator to its first suspension (subscribed, awaiting an event)."""
    task = asyncio.get_running_loop().create_task(gen.__anext__())
    await asyncio.sleep(0)  # let subscribe() register its queue
    return task


async def test_disconnect_cancels_run_when_enabled() -> None:
    bus, executor = EventBus(), _RecordingExecutor()
    gen = _run_event_gen(_svc(bus, executor), "r1", 0, cancel_on_disconnect=True)
    task = await _start(gen)
    bus.publish(RunEvent(event="node_started", run_id="r1", thread_id="t1", data={}))
    await task  # first frame delivered — run still going
    # client goes away mid-run → generator torn down before any terminal event
    await gen.aclose()
    assert executor.cancelled == ["r1"]


async def test_disconnect_does_not_cancel_when_disabled() -> None:
    bus, executor = EventBus(), _RecordingExecutor()
    gen = _run_event_gen(_svc(bus, executor), "r2", 0, cancel_on_disconnect=False)
    task = await _start(gen)
    bus.publish(RunEvent(event="node_started", run_id="r2", thread_id="t1", data={}))
    await task
    await gen.aclose()
    assert executor.cancelled == []


async def test_normal_completion_never_cancels() -> None:
    """A run that reaches run_finished must not be cancelled by teardown."""
    bus, executor = EventBus(), _RecordingExecutor()
    gen = _run_event_gen(_svc(bus, executor), "r3", 0, cancel_on_disconnect=True)
    task = await _start(gen)
    # terminal event → subscribe() returns → generator sets finished=True
    bus.publish(RunEvent(event="run_finished", run_id="r3", thread_id="t1", data={}))
    await task  # yields the run_finished frame
    frames = [frame async for frame in gen]  # drain to StopAsyncIteration
    assert frames == []  # nothing after the terminal frame
    await gen.aclose()  # idempotent — generator already exhausted
    assert executor.cancelled == []
