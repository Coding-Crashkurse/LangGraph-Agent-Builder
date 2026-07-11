"""Router — merged Rule/LLM router (palette v2, SPEC §5.5, §12.3).

One palette node with a ``mode`` switch replacing the two legacy routers:

* ``rules`` → predicate table (successor of ``lab.flow.rule_router``): one ROUTE
  output per distinct rule label plus the default label.
* ``llm``   → label classification (successor of ``lab.flow.llm_router``): one
  ROUTE output per configured label; the classifier model stays an **inline**
  ModelInput (a router's throwaway classifier is not a shared resource).

``build`` delegates to the legacy classes' node functions — the field union is a
superset of both, so their ``ctx.get_field(...)`` reads resolve unchanged.
"""

from __future__ import annotations

from langgraph_agent_builder.components.flow_control.routers import LLMRouter, RuleRouter
from langgraph_agent_builder.sdk import BuildContext, Component, NodeKind, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeConfig, NodeFn
from langgraph_agent_builder.sdk.fields import MultiselectInput


class Router(Component):
    component_id = "lab.flow.router"
    display_name = "Router"
    description = "Branch on predicate rules or LLM label classification (mode switch)."
    icon = "git-branch"
    category = "flow_control"
    node_kind = NodeKind.ROUTER
    dynamic_outputs_from = "labels"  # drives the dynamic handle UI in llm mode

    inputs = [
        fields.DropdownInput(
            name="mode",
            display_name="Mode",
            options=["rules", "llm"],
            default="rules",
            info="`rules`: predicate table. `llm`: classify into labels.",
        ),
        # --- rules mode ---
        fields.TableInput(
            name="rules",
            display_name="Rules",
            info='Rows of label + predicate, e.g. `"refund" in message`. First match wins.',
            columns=[
                fields.ColumnSpec(name="label", type="str"),
                fields.ColumnSpec(name="when", type="str"),
            ],
        ),
        fields.StrInput(name="default_label", display_name="Default Label", default="default"),
        # --- llm mode ---
        fields.MultiselectInput(
            name="labels",
            display_name="Labels",
            info="Branch labels — one amber output handle per label.",
        ),
        fields.ModelInput(
            name="model",
            display_name="Model",
            info="Optional inline classifier; without one, keyword matching routes.",
        ),
        fields.MultilineInput(
            name="instructions",
            display_name="Instructions",
            info="Extra classification guidance for the model.",
            advanced=True,
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]

    @classmethod
    def outputs_for_config(cls, config: NodeConfig) -> list[Output]:
        mode = str(config.get("mode") or "rules")
        if mode == "llm":
            labels = config.get("labels") or []
            if not labels:
                f = cls.field_map().get("labels")
                if isinstance(f, MultiselectInput):
                    labels = f.default or []
            return [Output(name=str(lb), port=ports.ROUTE) for lb in labels]
        # rules mode — distinct rule labels + default (mirrors RuleRouter)
        out_labels: list[str] = []
        for row in config.get("rules") or []:
            label = str(row.get("label", "")).strip()
            if label and label not in out_labels:
                out_labels.append(label)
        default = str(config.get("default_label") or "default")
        if default not in out_labels:
            out_labels.append(default)
        return [Output(name=lb, port=ports.ROUTE) for lb in out_labels]

    def build(self, ctx: BuildContext) -> NodeFn:
        mode = str(ctx.get_field("mode") or "rules")
        if mode == "llm":
            return LLMRouter().build(ctx)
        return RuleRouter().build(ctx)
