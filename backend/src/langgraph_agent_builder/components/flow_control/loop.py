"""Loop — merged For-Each / Loop-Until (palette v2, SPEC §5.5, §12.3).

One palette node with a ``mode`` switch replacing the two legacy loop nodes:

* ``collection`` → map a template over a list (successor of ``lab.data.for_each``);
  a TASK emitting ``results`` (Table) + ``text`` (joined Text).
* ``until``      → cycle helper with a counter guard (successor of
  ``lab.flow.loop_until``); a ROUTER emitting ``continue`` / ``done`` routes.

``build``/``node_kind``/``outputs`` all branch on ``mode``; ``build`` delegates to
the legacy classes' node functions (their field reads are a subset of Loop's
field union). Loop-durability / checkpoint-cursor is a later phase — this
replicates the existing self-contained in-node behavior.
"""

from __future__ import annotations

from langgraph_agent_builder.components.data.batch import ForEach
from langgraph_agent_builder.components.flow_control.loop_until import LoopUntil
from langgraph_agent_builder.sdk import BuildContext, Component, NodeKind, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeConfig, NodeFn


class Loop(Component):
    component_id = "lab.flow.loop"
    display_name = "Loop"
    description = (
        "Map a template over a collection, or cycle until a condition holds (mode switch)."
    )
    icon = "repeat"
    category = "flow_control"
    node_kind = NodeKind.TASK  # default (collection); `until` mode → ROUTER

    inputs = [
        fields.DropdownInput(
            name="mode",
            display_name="Mode",
            options=["collection", "until"],
            default="collection",
            info="`collection`: map over a list. `until`: loop with a done condition.",
        ),
        # --- collection mode ---
        fields.MultilineInput(
            name="template",
            display_name="Item Template",
            info="Sandboxed jinja rendered once per item. Available: {{ item }}, {{ index }}, "
            "and for Documents {{ page_content }} / {{ metadata }}.",
            default="{{ item }}",
        ),
        fields.StrInput(
            name="separator",
            display_name="Join Separator",
            default="\n",
            advanced=True,
            info="Separator used to build the aggregated `text` output.",
        ),
        fields.HandleField(name="items", display_name="Items", as_port=ports.ANY),
        # --- until mode ---
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

    @classmethod
    def node_kind_for_config(cls, config: NodeConfig) -> NodeKind:
        return (
            NodeKind.ROUTER if str(config.get("mode") or "collection") == "until" else NodeKind.TASK
        )

    @classmethod
    def outputs_for_config(cls, config: NodeConfig) -> list[Output]:
        if str(config.get("mode") or "collection") == "until":
            return [
                Output(name="continue", display_name="Continue", port=ports.ROUTE),
                Output(name="done", display_name="Done", port=ports.ROUTE),
            ]
        return [
            Output(name="results", display_name="Results", port=ports.TABLE),
            Output(name="text", display_name="Text", port=ports.TEXT),
        ]

    def build(self, ctx: BuildContext) -> NodeFn:
        mode = str(ctx.get_field("mode") or "collection")
        if mode == "until":
            return LoopUntil().build(ctx)
        return ForEach().build(ctx)
