"""LangGraphAgentExecutor — the A2A <-> LangGraph bridge.

The mapping table in CLAUDE.md §9.2 is normative:
  contextId == thread_id, one task == one graph run, custom emit -> working
  DataPart update, interrupt -> input_required (final), follow-up message ->
  Command(resume=...), final assistant message -> artifact + completed,
  cancel -> asyncio cancel + canceled, exception -> failed.

Every run (external clients and the debug UI alike) goes through this class.
"""

import asyncio
import logging
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import DataPart, Message, Part, TaskState, TextPart
from a2a.utils import get_message_text, new_task
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from graphforge.components.templating import message_text
from graphforge.runtime.events import EventBus
from graphforge.runtime.runs import RunLog

logger = logging.getLogger(__name__)


class RunRegistry:
    """Tracks the asyncio task of each in-flight run so tasks/cancel works."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def register(self, run_id: str, task: asyncio.Task[Any]) -> None:
        self._tasks[run_id] = task

    def unregister(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True


def _resume_value(message: Message | None) -> Any:
    """Resume payload for Command(resume=...): prefer the first DataPart's dict
    (debug-UI approvals), fall back to the plain text."""
    if message is not None:
        for part in message.parts or []:
            if isinstance(part.root, DataPart):
                return part.root.data
    return get_message_text(message) if message is not None else ""


def _as_data(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {"value": payload}


def _summarize_update(update: Any) -> dict[str, Any]:
    if isinstance(update, dict):
        summary: dict[str, Any] = {"keys": sorted(update.keys())}
        messages = update.get("messages")
        if isinstance(messages, list) and messages:
            summary["last_message"] = message_text(messages[-1])[:300]
        if "route" in update:
            summary["route"] = update["route"]
        return summary
    return {"repr": str(update)[:200]}


def extract_final_text(state_values: dict[str, Any]) -> str:
    messages = state_values.get("messages") or []
    for message in reversed(messages):
        if getattr(message, "type", "") == "ai":
            return message_text(message)
    return message_text(messages[-1]) if messages else ""


class LangGraphAgentExecutor(AgentExecutor):
    def __init__(
        self,
        graph: Any,
        *,
        flow_id: str,
        flow_slug: str,
        bus: EventBus,
        run_log: RunLog,
        runs: RunRegistry,
    ) -> None:
        self.graph = graph
        self.flow_id = flow_id
        self.flow_slug = flow_slug
        self.bus = bus
        self.run_log = run_log
        self.runs = runs

    # -- helpers -------------------------------------------------------------

    def _publish(
        self, task_id: str, type: str, data: dict[str, Any], node: str | None = None
    ) -> None:
        self.bus.publish_event(
            task_id=task_id,
            flow_id=self.flow_id,
            source="a2a",
            type=type,
            node=node,
            data=data,
        )

    async def _log_state(
        self,
        task_id: str,
        context_id: str,
        state: str,
        input_preview: str | None = None,
        error: str | None = None,
    ) -> None:
        await self.run_log.upsert(
            run_id=task_id,
            flow_id=self.flow_id,
            context_id=context_id,
            source="a2a",
            state=state,
            input_preview=input_preview,
            error=error,
        )

    # -- AgentExecutor -------------------------------------------------------

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            if context.message is None:
                raise ValueError("request contains neither a task nor a message")
            task = new_task(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        config = {"configurable": {"thread_id": task.context_id}}
        user_text = get_message_text(context.message) if context.message else ""

        self._publish(
            task.id,
            "status",
            {"state": "submitted", "input": user_text[:500], "context_id": task.context_id},
        )
        await self._log_state(task.id, task.context_id, "submitted", input_preview=user_text)

        current = asyncio.current_task()
        if current is not None:
            self.runs.register(task.id, current)
        # Everything that can fail lives inside this try: an escaped exception
        # would abort the SSE stream mid-chunk instead of yielding a clean
        # `failed` task (and takes the self-client in the debug API down with it).
        try:
            snapshot = await self.graph.aget_state(config)
            resuming = bool(snapshot.tasks and any(t.interrupts for t in snapshot.tasks))
            graph_input: Any
            if resuming:
                graph_input = Command(resume=_resume_value(context.message))
            else:
                graph_input = {"messages": [HumanMessage(content=user_text)]}

            await updater.start_work()
            self._publish(task.id, "status", {"state": "working"})
            await self._log_state(task.id, task.context_id, "working")

            async for mode, chunk in self.graph.astream(
                graph_input, config, stream_mode=["custom", "updates", "debug"]
            ):
                if mode == "custom":
                    payload = _as_data(chunk)
                    await updater.update_status(
                        TaskState.working,
                        message=updater.new_agent_message(
                            parts=[Part(root=DataPart(data=payload))]
                        ),
                    )
                    self._publish(
                        task.id,
                        f"custom.{payload.get('type', 'event')}",
                        payload.get("data") or {},
                        node=payload.get("node"),
                    )
                elif mode == "updates":
                    if "__interrupt__" in chunk:
                        payload = _as_data(chunk["__interrupt__"][0].value)
                        await updater.update_status(
                            TaskState.input_required,
                            message=updater.new_agent_message(
                                parts=[Part(root=DataPart(data=payload))]
                            ),
                            final=True,
                        )
                        self._publish(task.id, "interrupt", payload, node=payload.get("node"))
                        await self._log_state(task.id, task.context_id, "input-required")
                        return
                    for node_name, update in chunk.items():
                        self._publish(
                            task.id, "node.update", _summarize_update(update), node=node_name
                        )
                elif mode == "debug":
                    debug_type = chunk.get("type")
                    node_name = (chunk.get("payload") or {}).get("name")
                    if debug_type == "task" and node_name:
                        self._publish(task.id, "node.start", {}, node=node_name)
                    elif debug_type == "task_result" and node_name:
                        self._publish(task.id, "node.end", {}, node=node_name)

            state = await self.graph.aget_state(config)
            final_text = extract_final_text(state.values)
            await updater.add_artifact([Part(root=TextPart(text=final_text))], name="response")
            await updater.complete()
            self._publish(task.id, "artifact", {"text": final_text[:2000]})
            self._publish(task.id, "status", {"state": "completed"})
            await self._log_state(task.id, task.context_id, "completed")
        except asyncio.CancelledError:
            # cancel() already enqueued the canceled status on the cancel queue;
            # here we only record it internally, then let cancellation propagate.
            self._publish(task.id, "status", {"state": "canceled"})
            await self._log_state(task.id, task.context_id, "canceled")
            raise
        except Exception as exc:
            logger.exception("flow '%s' task %s failed", self.flow_slug, task.id)
            await updater.failed(
                message=updater.new_agent_message(parts=[Part(root=TextPart(text=str(exc)))])
            )
            self._publish(task.id, "error", {"message": str(exc)})
            await self._log_state(task.id, task.context_id, "failed", error=str(exc))
        finally:
            self.runs.unregister(task.id)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            return
        was_running = self.runs.cancel(task.id)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.cancel()
        # bus/run-log bookkeeping happens in execute()'s CancelledError handler;
        # if no run was in flight, record the terminal state here instead.
        if not was_running:
            self._publish(task.id, "status", {"state": "canceled"})
            await self._log_state(task.id, task.context_id, "canceled")
