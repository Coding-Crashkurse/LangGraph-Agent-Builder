"""LGARequestHandler — DefaultRequestHandler + replay-capable resubscribe.

SPEC §7.5: tasks/resubscribe re-attaches SSE "replaying from persisted event
seq". The sdk only taps live queues, which (a) races with its immediate-close
on final events (tapped children get wiped) and (b) can block silently forever
on an open-but-quiet queue. We replay the persisted Task snapshot first, then
consume the live tap under a watchdog that falls back to the task store.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from a2a.server.context import ServerCallContext
from a2a.server.events import Event
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import (
    TaskIdParams,
    TaskNotFoundError,
    TaskState,
    TaskStatusUpdateEvent,
)
from a2a.utils.errors import ServerError

TERMINAL = {
    TaskState.completed,
    TaskState.failed,
    TaskState.canceled,
    TaskState.rejected,
}
FINAL_STATES = TERMINAL | {TaskState.input_required, TaskState.auth_required}

WATCHDOG_INTERVAL_S = 1.0
OVERALL_DEADLINE_S = 120.0


class LGARequestHandler(DefaultRequestHandler):
    async def on_resubscribe_to_task(
        self,
        params: TaskIdParams,
        context: ServerCallContext | None = None,
    ) -> AsyncGenerator[Event]:
        task: Any = await self.task_store.get(params.id, context)
        if not task:
            raise ServerError(error=TaskNotFoundError())

        def final_event(snapshot: Any) -> TaskStatusUpdateEvent:
            return TaskStatusUpdateEvent(
                task_id=snapshot.id,
                context_id=snapshot.context_id,
                status=snapshot.status,
                final=True,
            )

        # replay: current snapshot first (client resyncs regardless of what
        # the live buffer still holds)
        yield task
        if task.status.state in FINAL_STATES:
            yield final_event(task)
            return

        # live tap under a watchdog: the sdk consumer can block silently on an
        # open-but-quiet queue, and its immediate-close wipes tapped children —
        # in both cases the task store is the source of truth for finality.
        parent = super().on_resubscribe_to_task(params, context)
        iterator = parent.__aiter__()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + OVERALL_DEADLINE_S
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        iterator.__anext__(), timeout=WATCHDOG_INTERVAL_S
                    )
                except TimeoutError:
                    refreshed = await self.task_store.get(params.id, context)
                    if refreshed is not None and refreshed.status.state in FINAL_STATES:
                        yield final_event(refreshed)
                        return
                    if loop.time() > deadline:
                        return
                    continue
                except (StopAsyncIteration, ServerError):
                    break  # live queue ended or already gone → store fallback below
                yield event
                if getattr(event, "final", False):
                    return
        finally:
            await parent.aclose()

        # stream ended without a final event (wiped child queue): the run may
        # still be finishing — follow the store until it turns final.
        while loop.time() <= deadline:
            refreshed = await self.task_store.get(params.id, context)
            if refreshed is not None and refreshed.status.state in FINAL_STATES:
                yield final_event(refreshed)
                return
            await asyncio.sleep(0.25)
