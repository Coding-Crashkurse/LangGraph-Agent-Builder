"""FastMCP app factory for a flow (CLAUDE.md §10).

One tool per flow: (message, thread_id?) -> str. `thread_id` gives MCP callers
the same conversation continuity A2A gets via contextId. Custom events are
forwarded as progress/log notifications and mirrored to the debug bus. If the
graph interrupts, the tool fails fast pointing at the A2A endpoint — unless
`settings.enable_mcp_elicitation` is on and the client supports elicitation.
"""

import asyncio
import logging
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from graphforge.a2a.card import build_agent_card
from graphforge.a2a.executor import RunRegistry, extract_final_text
from graphforge.compiler.spec import FlowSpec
from graphforge.runtime.events import EventBus
from graphforge.runtime.runs import RunLog
from graphforge.settings import Settings

logger = logging.getLogger(__name__)

_HITL_ERROR = (
    "This flow paused for human input, which MCP tool calls cannot collect. "
    "Use the A2A endpoint for approval-style flows (see the agent card resource)."
)


class HumanReply(BaseModel):
    """Elicitation schema used when settings.enable_mcp_elicitation is on."""

    approve: bool = Field(True, description="Approve the pending step?")
    text: str = Field("", description="Free-text input / reviewer comment.")


def build_mcp_server(
    spec: FlowSpec,
    graph: Any,
    *,
    settings: Settings,
    bus: EventBus,
    run_log: RunLog,
    runs: RunRegistry,
) -> FastMCP:
    tool_spec = spec.publish.mcp_tool
    flow_id = spec.id or spec.slug
    server = FastMCP(
        name=spec.publish.agent_card.name or spec.name,
        instructions=spec.publish.agent_card.description or spec.description,
        stateless_http=True,
        streamable_http_path="/",
    )

    def publish(run_id: str, type: str, data: dict[str, Any], node: str | None = None) -> None:
        bus.publish_event(
            task_id=run_id, flow_id=flow_id, source="mcp", type=type, node=node, data=data
        )

    async def log_state(
        run_id: str,
        thread_id: str,
        state: str,
        input_preview: str | None = None,
        error: str | None = None,
    ) -> None:
        await run_log.upsert(
            run_id=run_id,
            flow_id=flow_id,
            context_id=thread_id,
            source="mcp",
            state=state,
            input_preview=input_preview,
            error=error,
        )

    async def run_flow(message: str, thread_id: str | None, ctx: Context) -> str:
        thread = thread_id or f"mcp-{uuid4().hex[:12]}"
        run_id = f"mcp-{uuid4().hex[:12]}"
        config = {"configurable": {"thread_id": thread}}
        publish(
            run_id, "status", {"state": "working", "input": message[:500], "context_id": thread}
        )
        await log_state(run_id, thread, "working", input_preview=message)

        current = asyncio.current_task()
        if current is not None:
            runs.register(run_id, current)

        graph_input: Any = {"messages": [HumanMessage(content=message)]}
        progress = 0
        try:
            snapshot = await graph.aget_state(config)
            if snapshot.tasks and any(t.interrupts for t in snapshot.tasks):
                # thread is blocked on an earlier interrupt; a plain message cannot resume it
                await log_state(run_id, thread, "failed", error=_HITL_ERROR)
                publish(run_id, "error", {"message": _HITL_ERROR})
                raise ToolError(_HITL_ERROR)

            while True:
                interrupt_payload: dict[str, Any] | None = None
                async for mode, chunk in graph.astream(
                    graph_input, config, stream_mode=["custom", "updates", "debug"]
                ):
                    if mode == "custom":
                        payload = chunk if isinstance(chunk, dict) else {"value": chunk}
                        progress += 1
                        event_type = str(payload.get("type", "event"))
                        await ctx.report_progress(progress, None, message=event_type)
                        await ctx.info(f"{event_type}: {payload.get('data')}")
                        publish(
                            run_id,
                            f"custom.{event_type}",
                            payload.get("data") or {},
                            node=payload.get("node"),
                        )
                    elif mode == "updates":
                        if "__interrupt__" in chunk:
                            value = chunk["__interrupt__"][0].value
                            interrupt_payload = (
                                value if isinstance(value, dict) else {"value": value}
                            )
                            break
                        for node_name, update in chunk.items():
                            keys = sorted(update.keys()) if isinstance(update, dict) else []
                            publish(run_id, "node.update", {"keys": keys}, node=node_name)
                    elif mode == "debug":
                        debug_type = chunk.get("type")
                        node_name = (chunk.get("payload") or {}).get("name")
                        if debug_type == "task" and node_name:
                            publish(run_id, "node.start", {}, node=node_name)
                        elif debug_type == "task_result" and node_name:
                            publish(run_id, "node.end", {}, node=node_name)

                if interrupt_payload is None:
                    break
                publish(run_id, "interrupt", interrupt_payload, node=interrupt_payload.get("node"))
                if not settings.enable_mcp_elicitation:
                    await log_state(run_id, thread, "failed", error=_HITL_ERROR)
                    raise ToolError(_HITL_ERROR)
                await log_state(run_id, thread, "input-required")
                try:
                    result = await ctx.elicit(
                        message=str(interrupt_payload.get("prompt", "Input required")),
                        schema=HumanReply,
                    )
                except Exception as exc:
                    await log_state(run_id, thread, "failed", error=_HITL_ERROR)
                    raise ToolError(_HITL_ERROR) from exc
                if getattr(result, "action", "") != "accept" or result.data is None:
                    await log_state(run_id, thread, "canceled")
                    raise ToolError("Reviewer declined the elicitation request.")
                graph_input = Command(
                    resume={
                        "approved": result.data.approve,
                        "comment": result.data.text,
                        "text": result.data.text,
                    }
                )
                await log_state(run_id, thread, "working")

            state = await graph.aget_state(config)
            final_text = extract_final_text(state.values)
            publish(run_id, "artifact", {"text": final_text[:2000]})
            publish(run_id, "status", {"state": "completed"})
            await log_state(run_id, thread, "completed")
            return final_text
        except asyncio.CancelledError:
            publish(run_id, "status", {"state": "canceled"})
            await log_state(run_id, thread, "canceled")
            raise
        except ToolError:
            raise
        except Exception as exc:
            logger.exception("mcp run %s failed", run_id)
            publish(run_id, "error", {"message": str(exc)})
            await log_state(run_id, thread, "failed", error=str(exc))
            raise ToolError(str(exc)) from exc
        finally:
            runs.unregister(run_id)

    @server.tool(name=tool_spec.name, description=tool_spec.description)
    async def run(message: str, thread_id: str | None = None, ctx: Context = None) -> str:  # type: ignore[assignment]
        return await run_flow(message, thread_id, ctx)

    @server.resource(
        "resource://agent-card",
        name="agent-card",
        description="A2A agent card of this flow (discovery parity).",
        mime_type="application/json",
    )
    def agent_card() -> str:
        card = build_agent_card(spec, settings, include_rest=False)
        return card.model_dump_json(exclude_none=True, by_alias=True)

    return server
