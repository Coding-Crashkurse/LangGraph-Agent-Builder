"""Unit tests for lga.components.data.batch (_as_items / _item_context branches)."""

from __future__ import annotations

from lga.components.data.batch import ForEach, _as_items, _item_context
from lga.sdk.ports import Document, Message
from lga.sdk.testing import ComponentTestHarness

# --------------------------------------------------------------------------- _as_items


def test_as_items_none_is_empty() -> None:
    assert _as_items(None) == []


def test_as_items_list_passthrough() -> None:
    assert _as_items([1, 2]) == [1, 2]


def test_as_items_dict_with_rows_unwraps() -> None:
    assert _as_items({"rows": [{"a": 1}, {"a": 2}]}) == [{"a": 1}, {"a": 2}]


def test_as_items_dict_without_rows_wraps_self() -> None:
    assert _as_items({"a": 1}) == [{"a": 1}]


def test_as_items_dict_with_non_list_rows_wraps_self() -> None:
    payload = {"rows": "not-a-list"}
    assert _as_items(payload) == [payload]


def test_as_items_scalar_wraps() -> None:
    assert _as_items("solo") == ["solo"]


# --------------------------------------------------------------------------- _item_context


def test_item_context_document_exposes_fields() -> None:
    ctx = _item_context(Document(page_content="body", metadata={"k": 1}), 3)
    assert ctx["index"] == 3
    assert ctx["page_content"] == "body"
    assert ctx["metadata"] == {"k": 1}
    assert ctx["item"] == {"page_content": "body", "metadata": {"k": 1}}


def test_item_context_message_exposes_content() -> None:
    ctx = _item_context(Message(role="user", content="hey"), 0)
    assert ctx["item"] == "hey"


def test_item_context_plain_value() -> None:
    ctx = _item_context(42, 7)
    assert ctx["item"] == 42
    assert ctx["index"] == 7


# --------------------------------------------------------------------------- node behaviour


async def test_for_each_unwraps_json_rows() -> None:
    node = ComponentTestHarness().build(
        ForEach,
        config={"template": "{{ item.v }}", "separator": "|"},
        ports={"items": {"rows": [{"v": "a"}, {"v": "b"}]}},
    )
    out = await node()
    assert out["text"] == "a|b"
    assert out["results"] == [{"index": 0, "result": "a"}, {"index": 1, "result": "b"}]


async def test_for_each_messages_render_content() -> None:
    node = ComponentTestHarness().build(
        ForEach,
        config={"template": "{{ item }}"},
        ports={"items": [Message(role="user", content="one"), Message(role="user", content="two")]},
    )
    out = await node()
    assert out["text"] == "one\ntwo"
