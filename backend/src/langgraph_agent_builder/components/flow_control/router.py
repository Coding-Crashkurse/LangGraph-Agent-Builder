"""Router — merged Rule/LLM router (palette v2, SPEC §5.5, §12.3).

One palette node with a ``mode`` switch:

* ``rules`` → predicate table: one ROUTE output per distinct rule label plus the
  default label. First matching (sandboxed jinja) predicate wins.
* ``llm``   → label classification: one ROUTE output per configured label; the
  classifier model stays an **inline** ModelInput (a router's throwaway
  classifier is not a shared resource). Without a model, keyword matching routes.
"""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.sdk import BuildContext, Component, NodeKind, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeConfig, NodeFn
from langgraph_agent_builder.sdk.fields import MultiselectInput
from langgraph_agent_builder.sdk.runtime import get_run_context
from langgraph_agent_builder.sdk.templating import eval_predicate, last_message_text


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
        # rules mode — distinct rule labels + default
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
            return self._build_llm(ctx)
        return self._build_rules(ctx)

    def _build_llm(self, ctx: BuildContext) -> NodeFn:
        labels = [str(x) for x in ctx.get_field("labels") or []]

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rc = get_run_context(config)
            text = last_message_text(state)
            model_cfg = ctx.get_input(state, "model")
            label: str | None = None
            if model_cfg:
                from langgraph_agent_builder.components.llm._models import resolve_model

                model = resolve_model(model_cfg)
                prompt = (
                    "Classify the user message into exactly one of these labels: "
                    f"{', '.join(labels)}.\n"
                    f"{ctx.get_field('instructions') or ''}\n"
                    f"Message: {text}\n"
                    "Reply with the label only."
                )
                response = await model.ainvoke(prompt)
                raw = (
                    (
                        response.content
                        if isinstance(response.content, str)
                        else str(response.content)
                    )
                    .strip()
                    .lower()
                )
                label = next((lb for lb in labels if lb.lower() == raw), None) or next(
                    (lb for lb in labels if lb.lower() in raw), None
                )
            else:
                lowered = text.lower()
                label = next((lb for lb in labels if lb.lower() == lowered), None) or next(
                    (lb for lb in labels if lb.lower() in lowered), None
                )
            if label is None:
                # no match → last label (catch-all by convention, e.g. "other")
                label = labels[-1] if labels else ""
            rc.emit_status(f"routed → {label}")
            return {"route": label}

        return node

    def _build_rules(self, ctx: BuildContext) -> NodeFn:
        rules = list(ctx.get_field("rules") or [])
        default = str(ctx.get_field("default_label") or "default")

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            variables = {
                "data": dict(state.get("data") or {}),
                "message": last_message_text(state),
                "route": dict(state.get("route") or {}),
            }
            for row in rules:
                predicate = str(row.get("when", "")).strip()
                label = str(row.get("label", "")).strip()
                if not predicate or not label:
                    continue
                try:
                    if eval_predicate(predicate, variables):
                        return {"route": label}
                except Exception:
                    continue  # broken predicate never matches
            return {"route": default}

        return node
