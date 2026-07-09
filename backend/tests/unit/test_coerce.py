"""Unit tests for lga.sdk.ports.coerce (registered edge coercions, SPEC §4.3)."""

from __future__ import annotations

import pytest

from lga.sdk.ports import (
    DOCUMENTS,
    JSON,
    MESSAGE,
    TABLE,
    TEXT,
    Document,
    Message,
    coerce,
)


def test_message_to_text_from_message() -> None:
    assert coerce.message_to_text(Message(role="user", content="hi")) == "hi"


def test_message_to_text_from_dict() -> None:
    assert coerce.message_to_text({"content": "from-dict"}) == "from-dict"


def test_message_to_text_from_dict_missing_content() -> None:
    assert coerce.message_to_text({"other": 1}) == ""


def test_message_to_text_from_scalar() -> None:
    assert coerce.message_to_text(123) == "123"


def test_text_to_message_wraps_as_user() -> None:
    msg = coerce.text_to_message("yo")
    assert isinstance(msg, Message)
    assert msg.role == "user"
    assert msg.content == "yo"


def test_text_to_message_stringifies_non_str() -> None:
    assert coerce.text_to_message(7).content == "7"


def test_documents_to_text_mixed_inputs() -> None:
    docs = [
        Document(page_content="doc-a"),
        {"page_content": "doc-b"},
        {"nope": 1},  # dict without page_content → ""
        "plain-string",
    ]
    assert coerce.documents_to_text(docs) == "doc-a\n\ndoc-b\n\n\n\nplain-string"


def test_documents_to_text_none_is_empty() -> None:
    assert coerce.documents_to_text(None) == ""


def test_json_to_text_pretty_prints() -> None:
    assert coerce.json_to_text({"b": 1}) == '{\n  "b": 1\n}'


def test_json_to_text_non_serializable_falls_back_to_str() -> None:
    # tuple dict-key is not serializable even with default=str → ValueError/TypeError → str()
    value = {(1, 2): "x"}
    assert coerce.json_to_text(value) == str(value)


def test_table_to_json_wraps_rows() -> None:
    rows = [{"a": 1}, {"a": 2}]
    assert coerce.table_to_json(rows) == {"rows": rows}


def test_table_to_json_none() -> None:
    assert coerce.table_to_json(None) == {"rows": []}


def test_table_to_text_empty() -> None:
    assert coerce.table_to_text([]) == ""
    assert coerce.table_to_text(None) == ""


def test_table_to_text_markdown() -> None:
    rows = [{"name": "Ada", "age": 36}, {"name": "Bob"}]
    out = coerce.table_to_text(rows)
    assert out.splitlines() == [
        "| name | age |",
        "| --- | --- |",
        "| Ada | 36 |",
        "| Bob |  |",  # missing column → empty cell
    ]


def test_table_to_text_no_dict_columns() -> None:
    # rows present but none are dicts → no columns → newline-joined str fallback
    assert coerce.table_to_text([1, 2, 3]) == "1\n2\n3"


def test_table_to_text_non_dict_row_among_dicts() -> None:
    # a non-dict row yields all-empty cells for the derived columns
    rows = [{"k": "v"}, "loose"]
    out = coerce.table_to_text(rows)
    assert out.splitlines() == ["| k |", "| --- |", "| v |", "|  |"]


def test_wrap_list() -> None:
    assert coerce.wrap_list("x") == ["x"]


def test_find_registered_and_missing() -> None:
    assert coerce.find(MESSAGE, TEXT) == "message_to_text"
    assert coerce.find(DOCUMENTS, TEXT) == "documents_to_text"
    assert coerce.find(TABLE, JSON) == "table_to_json"
    # no registered coercion for this direction
    assert coerce.find(TEXT, DOCUMENTS) is None


def test_apply_single_and_chained() -> None:
    assert coerce.apply("message_to_text", Message(content="hi")) == "hi"
    # chained: message_to_text then wrap_list
    assert coerce.apply("message_to_text+wrap_list", Message(content="a")) == ["a"]


def test_apply_unknown_step_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        coerce.apply("no_such_coercion", "x")
