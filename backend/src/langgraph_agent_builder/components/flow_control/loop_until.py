"""Loop Until — cycle helper with a counter guard (SPEC §12.3, M4)."""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.sdk import BuildContext, Component, NodeKind, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeFn
from langgraph_agent_builder.sdk.templating import eval_predicate, last_message_text


class LoopUntil(Component):
    component_id = "lab.flow.loop_until"
    legacy = True
    successor = "lab.flow.loop"
    display_name = "Loop Until"
    description = "Routes `continue` until the condition holds or max_iterations is hit."
    icon = "refresh-cw"
    category = "flow_control"
    node_kind = NodeKind.ROUTER

    inputs = [
        fields.StrInput(
            name="condition",
            display_name="Done Condition",
            info="Sandboxed jinja expression over {data, message, iteration}, "
            'e.g. `"APPROVED" in message`. Empty = loop only bounded by max_iterations.',
        ),
        fields.IntInput(
            name="max_iterations", display_name="Max Iterations", default=5, min=1, max=100
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [
        Output(name="continue", display_name="Continue", port=ports.ROUTE),
        Output(name="done", display_name="Done", port=ports.ROUTE),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        counter_key = f"__loop_{ctx.node_id}"

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            data = dict(state.get("data") or {})
            iteration = int(data.get(counter_key, 0)) + 1
            condition = str(ctx.get_field("condition") or "").strip()
            done = iteration > int(ctx.get_field("max_iterations") or 5)
            if not done and condition:
                try:
                    done = eval_predicate(
                        condition,
                        {"data": data, "message": last_message_text(state), "iteration": iteration},
                    )
                except Exception:
                    done = False
            return {"route": "done" if done else "continue", "data": {counter_key: iteration}}

        return node
