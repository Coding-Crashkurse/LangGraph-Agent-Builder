"""Zero-dependency testing components (SPEC §12.7) — fake embeddings + mock data.

Keep every RAG example and CI run working without API keys or external services
(SPEC §1.5-6): deterministic hash embeddings + Langflow-parity Mock Data.
"""

from __future__ import annotations

from typing import Any

from lga.sdk import BuildContext, Component, Output, fields, ports
from lga.sdk.component import NodeFn

_LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua."
)


class FakeEmbeddings(Component):
    component_id = "lga.testing.fake_embeddings"
    display_name = "Fake Embeddings (testing)"
    description = "Deterministic hash embeddings — RAG without API keys."
    icon = "binary"
    category = "testing"

    inputs = [
        fields.IntInput(name="dim", display_name="Dimensions", default=32, min=2, max=1536),
    ]
    outputs = [Output(name="embedding", display_name="Embedding", port=ports.EMBEDDING)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {"embedding": {"provider": "fake", "dim": int(ctx.get_field("dim") or 32)}}

        return node


class MockData(Component):
    component_id = "lga.testing.mock_data"
    display_name = "Mock Data (testing)"
    description = "Emit sample Message / Json / Table data (Langflow parity)."
    icon = "table"
    category = "testing"

    inputs = [
        fields.IntInput(name="rows", display_name="Table Rows", default=50, min=1, max=500),
    ]
    outputs = [
        Output(name="message", display_name="Message", port=ports.MESSAGE),
        Output(name="json", display_name="Json", port=ports.JSON),
        Output(name="table", display_name="Table", port=ports.TABLE),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rows = int(ctx.get_field("rows") or 50)
            table = [
                {"id": i, "name": f"Item {i}", "value": (i * 7) % 100, "active": i % 2 == 0}
                for i in range(rows)
            ]
            return {
                "message": ports.Message(role="assistant", content=_LOREM),
                "json": {"lorem": _LOREM, "count": rows},
                "table": table,
            }

        return node
