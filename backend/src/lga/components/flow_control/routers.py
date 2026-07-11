"""Routers (SPEC §5.5, §12.3): LLM Router + Rule Router."""

from __future__ import annotations

from typing import Any

from lga.sdk import BuildContext, Component, NodeKind, Output, fields, ports
from lga.sdk.component import NodeConfig, NodeFn
from lga.sdk.runtime import get_run_context
from lga.sdk.templating import eval_predicate, last_message_text


class LLMRouter(Component):
    component_id = "lga.flow.llm_router"
    display_name = "LLM Router"
    description = (
        "Routes the conversation into one of the configured labels. Uses the "
        "configured model; without a model it falls back to keyword matching."
    )
    icon = "git-branch"
    category = "flow_control"
    node_kind = NodeKind.ROUTER
    dynamic_outputs_from = "labels"

    inputs = [
        fields.MultiselectInput(
            name="labels",
            display_name="Labels",
            info="Branch labels — one amber output handle per label.",
            required=True,
        ),
        fields.ModelInput(
            name="model",
            display_name="Model",
            info="Optional; without a model, keyword matching routes deterministically.",
            advanced=False,
        ),
        fields.MultilineInput(
            name="instructions",
            display_name="Instructions",
            info="Extra classification guidance for the model.",
            advanced=True,
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        labels = [str(x) for x in ctx.get_field("labels") or []]

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rc = get_run_context(config)
            text = last_message_text(state)
            model_cfg = ctx.get_input(state, "model")
            label: str | None = None
            if model_cfg:
                from lga.components.llm._models import resolve_model

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


class RuleRouter(Component):
    component_id = "lga.flow.rule_router"
    display_name = "Rule Router"
    description = "Routes on data/message predicates (sandboxed jinja expressions)."
    icon = "list-tree"
    category = "flow_control"
    node_kind = NodeKind.ROUTER

    inputs = [
        fields.TableInput(
            name="rules",
            display_name="Rules",
            info='Rows of label + predicate, e.g. `"refund" in message`. First match wins.',
            columns=[
                fields.ColumnSpec(name="label", type="str"),
                fields.ColumnSpec(name="when", type="str"),
            ],
            required=True,
        ),
        fields.StrInput(
            name="default_label", display_name="Default Label", default="default", required=True
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]

    @classmethod
    def outputs_for_config(cls, config: NodeConfig) -> list[Output]:
        labels: list[str] = []
        for row in config.get("rules") or []:
            label = str(row.get("label", "")).strip()
            if label and label not in labels:
                labels.append(label)
        default = str(config.get("default_label") or "default")
        if default not in labels:
            labels.append(default)
        return [Output(name=lb, port=ports.ROUTE) for lb in labels]

    def build(self, ctx: BuildContext) -> NodeFn:
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
