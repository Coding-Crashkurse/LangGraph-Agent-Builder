"""Batch / map component (SPEC §12.3): map a template over a list of items.

`data.for_each` is lab's v1 map primitive. It renders a sandboxed jinja template
once per item of a list input and emits both a Table of per-item results and a
joined Text — the common "iterate rows / documents, transform each" DX that
Langflow's Loop component serves.

The fuller version — fanning each item through a downstream *canvas subgraph* via
LangGraph ``Send`` (map-reduce over a body region) — remains SPEC §5.5 [M4]. This
component deliberately runs self-contained (one node function, no compiler
support) so it adds map/aggregate without touching the compile pipeline.
"""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.sdk import Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import BuildContext, NodeFn
from langgraph_agent_builder.sdk.ports import Document, Message
from langgraph_agent_builder.sdk.templating import render_jinja


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


class ForEach(Component):
    component_id = "lab.data.for_each"
    display_name = "For Each"
    description = "Map a sandboxed template over each list item → per-item Table + joined Text."
    icon = "list"
    category = "data"

    inputs = [
        fields.MultilineInput(
            name="template",
            display_name="Item Template",
            info="Sandboxed jinja rendered once per item. Available: {{ item }}, {{ index }}, "
            "and for Documents {{ page_content }} / {{ metadata }}.",
            default="{{ item }}",
            required=True,
        ),
        fields.StrInput(
            name="separator",
            display_name="Join Separator",
            default="\n",
            advanced=True,
            info="Separator used to build the aggregated `text` output.",
        ),
        fields.HandleField(name="items", display_name="Items", as_port=ports.ANY),
    ]
    outputs = [
        Output(name="results", display_name="Results", port=ports.TABLE),
        Output(name="text", display_name="Text", port=ports.TEXT),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            template = str(ctx.get_field("template") or "{{ item }}")
            separator = str(ctx.get_field("separator") or "\n")
            items = _as_items(ctx.get_input(state, "items"))
            rendered = [render_jinja(template, _item_context(it, i)) for i, it in enumerate(items)]
            results = [{"index": i, "result": r} for i, r in enumerate(rendered)]
            return {"results": results, "text": separator.join(rendered)}

        return node
