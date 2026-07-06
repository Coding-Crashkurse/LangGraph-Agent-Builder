"""LGARequestHandler — DefaultRequestHandler + replay-capable resubscribe.

SPEC §7.5: tasks/resubscribe re-attaches SSE "replaying from persisted event
seq". The sdk only taps live queues, which races with its immediate-close on
final events; we replay the persisted Task snapshot first and guarantee a
final event from the store when the live tap misses it.
"""

from __future__ import annotations

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


class LGARequestHandler(DefaultRequestHandler):
    async def on_resubscribe_to_task(
        self,
        params: TaskIdParams,
        context: ServerCallContext | None = None,
    ) -> AsyncGenerator[Event]:
        task: Any = await self.task_store.get(params.id, context)
        if not task:
            raise ServerError(error=TaskNotFoundError())

        # replay: current snapshot first (client resyncs regardless of what
        # the live buffer still holds)
        yield task
        if task.status.state in FINAL_STATES:
            yield TaskStatusUpdateEvent(
                task_id=task.id,
                context_id=task.context_id,
                status=task.status,
                final=True,
            )
            return

        delivered_final = False
        try:
            async for event in super().on_resubscribe_to_task(params, context):
                if getattr(event, "final", False):
                    delivered_final = True
                yield event
        except ServerError:
            pass  # live queue already gone — fall through to the store check

        if not delivered_final:
            import asyncio

            # the live queue can be wiped a beat before the aggregator persists
            # the final state — poll the store briefly instead of dropping it
            for _ in range(20):
                refreshed = await self.task_store.get(params.id, context)
                if refreshed is not None and refreshed.status.state in FINAL_STATES:
                    yield TaskStatusUpdateEvent(
                        task_id=refreshed.id,
                        context_id=refreshed.context_id,
                        status=refreshed.status,
                        final=True,
                    )
                    return
                await asyncio.sleep(0.1)
