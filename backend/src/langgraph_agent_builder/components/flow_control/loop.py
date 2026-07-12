"""Loop — merged For-Each / Loop-Until (palette v2, SPEC §5.5, §12.3).

One palette node with a ``mode`` switch:

* ``collection`` → map a template over a list; a TASK emitting ``results``
  (Table) + ``text`` (joined Text).
* ``until``      → cycle helper with a counter guard; a ROUTER emitting
  ``continue`` / ``done`` routes.
"""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.sdk import BuildContext, Component, NodeKind, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeConfig, NodeFn
from langgraph_agent_builder.sdk.ports import Document, Message
from langgraph_agent_builder.sdk.templating import eval_predicate, last_message_text, render_jinja


def _as_items(raw: Any) -> list[Any]:
    """Coerce a wired input into a list: Table/Documents/Messages/list stay,
    a Json ``{rows: [...]}`` unwraps, anything else becomes a one-item list."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        rows = raw.get("rows")
        return rows if isinstance(rows, list) else [raw]
    return [raw]


def _item_context(item: Any, index: int) -> dict[str, Any]:
    """Per-item jinja context. Documents/Messages expose their natural fields so
    templates read `{{ item }}` (or `{{ page_content }}`) without type juggling."""
    ctx: dict[str, Any] = {"index": index, "item": item}
    if isinstance(item, Document):
        ctx["item"] = {"page_content": item.page_content, "metadata": item.metadata}
        ctx["page_content"] = item.page_content
        ctx["metadata"] = item.metadata
    elif isinstance(item, Message):
        ctx["item"] = item.content
    return ctx


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
            return self._build_until(ctx)
        return self._build_collection(ctx)

    def _build_collection(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            template = str(ctx.get_field("template") or "{{ item }}")
            separator = str(ctx.get_field("separator") or "\n")
            items = _as_items(ctx.get_input(state, "items"))
            rendered = [render_jinja(template, _item_context(it, i)) for i, it in enumerate(items)]
            results = [{"index": i, "result": r} for i, r in enumerate(rendered)]
            return {"results": results, "text": separator.join(rendered)}

        return node

    def _build_until(self, ctx: BuildContext) -> NodeFn:
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
