"""Flow as Tool — a published flow becomes a Toolset entry (SPEC §12.5, M4)."""

from __future__ import annotations

from typing import Any

from lga.sdk import Component, Output, fields, ports
from lga.sdk.ports import LazyToolset, ToolDef


class FlowAsTool(Component):
    component_id = "lga.tools.flow_as_tool"
    display_name = "Flow as Tool"
    description = "Expose a published flow as a tool for an agent (in-process call)."
    icon = "workflow"
    category = "tools"

    inputs = [
        fields.StrInput(
            name="flow_slug",
            display_name="Flow Slug",
            required=True,
            info="Slug of a published flow on this server.",
        ),
        fields.StrInput(name="tool_name", display_name="Tool Name", advanced=True),
        fields.MultilineInput(
            name="tool_description", display_name="Tool Description", advanced=True
        ),
    ]
    outputs = [Output(name="toolset", display_name="Toolset", port=ports.TOOLSET)]

    def provide_tools(self, ctx) -> LazyToolset:
        slug = str(ctx.get_field("flow_slug") or "")
        tool_name = str(ctx.get_field("tool_name") or slug.replace("-", "_"))
        tool_description = str(ctx.get_field("tool_description") or "")

        async def factory() -> list[ToolDef]:
            from lga.services.locator import require_services

            svc = require_services("flow_as_tool")
            flow = await svc.flows.get_by_slug(slug)
            if flow is None:
                raise RuntimeError(f"flow {slug!r} not found")
            version = await svc.flows.serve_version(flow)
            if version is None:
                raise RuntimeError(f"flow {slug!r} has no published version")
            spec = version.flowspec

            async def run_child(message: str) -> str:
                _run_id, _thread, result = await svc.orchestrator.start_run(
                    spec=spec,
                    flow_row=flow,
                    mode="api",
                    input_text=message,
                    background=False,
                )
                if result.status != "completed":
                    raise RuntimeError(
                        f"child flow {slug} ended {result.status}: {result.error_message or ''}"
                    )
                return result.result_text

            description = tool_description or flow.description or flow.name
            return [
                ToolDef(
                    name=tool_name,
                    description=description,
                    args_schema={
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                    callable_ref=run_child,
                )
            ]

        return LazyToolset(factory)

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {}

        return node
