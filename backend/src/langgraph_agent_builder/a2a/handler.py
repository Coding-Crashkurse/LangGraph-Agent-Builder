"""LabRequestHandler — DefaultRequestHandler + replay-capable resubscribe.

SPEC §7.5: tasks/resubscribe re-attaches SSE "replaying from persisted event
seq". The sdk only taps live queues, which (a) races with its immediate-close
on final events (tapped children get wiped) and (b) can block silently forever
on an open-but-quiet queue. We replay the persisted Task snapshot first, then
consume the live tap under a watchdog that falls back to the task store.

Also enforces push-capability honesty (SPEC §7.9/§7.10): when the agent card
says `pushNotifications: false`, every `tasks/pushNotificationConfig/*` method
returns `-32003 PushNotificationNotSupported`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from a2a.server.context import ServerCallContext
from a2a.server.events import Event
from a2a.server.request_handlers import DefaultRequestHandler, JSONRPCHandler
from a2a.types import (
    DeleteTaskPushNotificationConfigParams,
    GetTaskPushNotificationConfigParams,
    JSONRPCErrorResponse,
    ListTaskPushNotificationConfigParams,
    PushNotificationNotSupportedError,
    SetTaskPushNotificationConfigRequest,
    SetTaskPushNotificationConfigResponse,
    TaskIdParams,
    TaskNotFoundError,
    TaskPushNotificationConfig,
    TaskStatusUpdateEvent,
)
from a2a.utils.errors import ServerError

from langgraph_agent_builder.a2a.tasks import FINAL_STATES

WATCHDOG_INTERVAL_S = 1.0
OVERALL_DEADLINE_S = 120.0


class LabRequestHandler(DefaultRequestHandler):
    def __init__(self, *args: Any, push_supported: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._push_supported = push_supported

    # ------------------------------------------------------ push honesty (§7.9)
    def _require_push_support(self) -> None:
        """Card says pushNotifications:false ⇒ -32003, not the sdk's -32004."""
        if not self._push_supported:
            raise ServerError(error=PushNotificationNotSupportedError())

    async def on_set_task_push_notification_config(
        self,
        params: TaskPushNotificationConfig,
        context: ServerCallContext | None = None,
    ) -> TaskPushNotificationConfig:
        self._require_push_support()
        return await super().on_set_task_push_notification_config(params, context)

    async def on_get_task_push_notification_config(
        self,
        params: TaskIdParams | GetTaskPushNotificationConfigParams,
        context: ServerCallContext | None = None,
    ) -> TaskPushNotificationConfig:
        self._require_push_support()
        return await super().on_get_task_push_notification_config(params, context)

    async def on_list_task_push_notification_config(
        self,
        params: ListTaskPushNotificationConfigParams,
        context: ServerCallContext | None = None,
    ) -> list[TaskPushNotificationConfig]:
        self._require_push_support()
        return await super().on_list_task_push_notification_config(params, context)

    async def on_delete_task_push_notification_config(
        self,
        params: DeleteTaskPushNotificationConfigParams,
        context: ServerCallContext | None = None,
    ) -> None:
        self._require_push_support()
        await super().on_delete_task_push_notification_config(params, context)

    # ------------------------------------------------------ resubscribe (§7.5)
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


class LabJSONRPCHandler(JSONRPCHandler):
    """JSONRPC-layer push honesty for `tasks/pushNotificationConfig/set`.

    The sdk's `@validate` gate on `set_push_notification_config` raises a bare
    ServerError when `capabilities.pushNotifications` is false, which surfaces
    as -32603/-32004 on the wire — SPEC §7.9/§7.10 pin -32003. Intercept before
    the gate; every other method reaches LabRequestHandler's own gates.
    """

    async def set_push_notification_config(
        self,
        request: SetTaskPushNotificationConfigRequest,
        context: ServerCallContext | None = None,
    ) -> SetTaskPushNotificationConfigResponse:
        if not self.agent_card.capabilities.push_notifications:
            return SetTaskPushNotificationConfigResponse(
                root=JSONRPCErrorResponse(id=request.id, error=PushNotificationNotSupportedError())
            )
        response: SetTaskPushNotificationConfigResponse = (
            await super().set_push_notification_config(request, context)
        )
        return response
