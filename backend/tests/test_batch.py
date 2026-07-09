"""data.for_each map/aggregate component (SPEC §12.3)."""

from __future__ import annotations

from lga.components.data.batch import ForEach
from lga.sdk.ports import Document
from lga.sdk.testing import ComponentTestHarness


async def test_for_each_maps_rows_to_table_and_text() -> None:
    node = ComponentTestHarness().build(
        ForEach,
        config={"template": "{{ item.name }}!", "separator": ", "},
        ports={"items": [{"name": "a"}, {"name": "b"}, {"name": "c"}]},
    )
    out = await node()
    assert out["text"] == "a!, b!, c!"
    assert out["results"] == [
        {"index": 0, "result": "a!"},
        {"index": 1, "result": "b!"},
        {"index": 2, "result": "c!"},
    ]


async def test_for_each_documents_expose_page_content() -> None:
    node = ComponentTestHarness().build(
        ForEach,
        config={"template": "{{ page_content }}"},
        ports={"items": [Document(page_content="one"), Document(page_content="two")]},
    )
    out = await node()
    assert out["text"] == "one\ntwo"


async def test_for_each_exposes_index() -> None:
    node = ComponentTestHarness().build(
        ForEach,
        config={"template": "{{ index }}:{{ item }}"},
        ports={"items": ["x", "y"]},
    )
    out = await node()
    assert out["text"] == "0:x\n1:y"


async def test_for_each_empty_input_is_safe() -> None:
    node = ComponentTestHarness().build(ForEach, config={}, ports={"items": None})
    out = await node()
    assert out["results"] == []
    assert out["text"] == ""


def test_for_each_is_registered() -> None:
    from lga.sdk.registry import get_registry

    assert get_registry().get("lga.data.for_each") is ForEach
