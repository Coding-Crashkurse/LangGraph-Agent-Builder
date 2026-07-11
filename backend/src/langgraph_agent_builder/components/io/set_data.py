"""Set Data — writes literal/expression-templated values into `data` (SPEC §12.1)."""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.sdk import BuildContext, Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeFn
from langgraph_agent_builder.sdk.expressions import render_expression


class SetData(Component):
    component_id = "lab.io.set_data"
    display_name = "Set Data"
    description = "Write literal or expression-templated values into the shared data dict."
    icon = "database"
    category = "io"

    inputs = [
        fields.TableInput(
            name="entries",
            display_name="Entries",
            info="Rows of key + template. Templates are bounded {{ … }} expressions over "
            "{input, state, vars}; a whole-cell expression keeps its typed value.",
            columns=[
                fields.ColumnSpec(name="key", type="str"),
                fields.ColumnSpec(name="template", type="str"),
            ],
            required=True,
            expressions=True,
        ),
        # trigger port so Set Data can be chained anywhere in the control flow
        fields.HandleField(name="input", display_name="Input", as_port=ports.ANY),
    ]
    outputs = [Output(name="data", display_name="Data", port=ports.JSON)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            scope = ctx.expr_scope(state)
            written: dict[str, Any] = {}
            for row in ctx.get_field("entries") or []:
                key = str(row.get("key", "")).strip()
                if not key:
                    continue
                written[key] = render_expression(str(row.get("template", "")), scope)
            return {"data": written}

        return node
