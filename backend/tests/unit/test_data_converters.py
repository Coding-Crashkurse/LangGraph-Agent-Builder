"""Unit tests for lga.components.data.converters.

PromptTemplate, TypeConvert (all conversion branches + dynamic ports/outputs),
JsonExtract (single/multi/scalar), Parser (regex named/unnamed/no-match, split).
"""

from __future__ import annotations

import json

from lga.components.data.converters import (
    CONVERSIONS,
    JsonExtract,
    Parser,
    PromptTemplate,
    TypeConvert,
)
from lga.sdk.ports import Document, Message
from lga.sdk.testing import ComponentTestHarness

# --------------------------------------------------------------------------- PromptTemplate


async def test_prompt_template_renders_from_state_data() -> None:
    node = ComponentTestHarness().build(PromptTemplate, config={"template": "Hi {name}"})
    out = await node({"data": {"name": "Ada"}})
    assert out["text"] == "Hi Ada"
    assert isinstance(out["message"], Message)
    assert out["message"].role == "user"
    assert out["message"].content == "Hi Ada"


async def test_prompt_template_prefers_wired_input_over_data() -> None:
    node = ComponentTestHarness().build(
        PromptTemplate, config={"template": "Hi {name}"}, ports={"name": "Grace"}
    )
    out = await node({"data": {"name": "Ada"}})
    assert out["text"] == "Hi Grace"


async def test_prompt_template_missing_var_renders_empty() -> None:
    node = ComponentTestHarness().build(PromptTemplate, config={"template": "Hi {name}!"})
    out = await node({})
    assert out["text"] == "Hi !"


# --------------------------------------------------------------------------- TypeConvert (runtime)


async def test_type_convert_message_to_text() -> None:
    node = ComponentTestHarness().build(
        TypeConvert,
        config={"conversion": "message_to_text"},
        ports={"input": Message(role="assistant", content="yo")},
    )
    out = await node()
    assert out["output"] == "yo"


async def test_type_convert_text_to_message() -> None:
    node = ComponentTestHarness().build(
        TypeConvert, config={"conversion": "text_to_message"}, ports={"input": "hello"}
    )
    out = await node()
    assert isinstance(out["output"], Message)
    assert out["output"].role == "user"
    assert out["output"].content == "hello"


async def test_type_convert_documents_to_text_mixed_items() -> None:
    docs = [
        Document(page_content="one", metadata={"k": 1}),
        {"page_content": "two"},
        42,
    ]
    node = ComponentTestHarness().build(
        TypeConvert,
        config={"conversion": "documents_to_text", "documents_template": "{{ page_content }}"},
        ports={"input": docs},
    )
    out = await node()
    assert out["output"] == "one\n\ntwo\n\n42"


async def test_type_convert_json_to_text() -> None:
    node = ComponentTestHarness().build(
        TypeConvert, config={"conversion": "json_to_text"}, ports={"input": {"a": 1}}
    )
    out = await node()
    assert json.loads(out["output"]) == {"a": 1}


async def test_type_convert_text_to_json_valid() -> None:
    node = ComponentTestHarness().build(
        TypeConvert, config={"conversion": "text_to_json"}, ports={"input": '{"x": 1}'}
    )
    out = await node()
    assert out["output"] == {"x": 1}


async def test_type_convert_text_to_json_invalid_wraps_raw() -> None:
    node = ComponentTestHarness().build(
        TypeConvert, config={"conversion": "text_to_json"}, ports={"input": "not json"}
    )
    out = await node()
    assert out["output"] == {"raw": "not json"}


async def test_type_convert_unknown_conversion_passes_through() -> None:
    node = ComponentTestHarness().build(
        TypeConvert, config={"conversion": "weird"}, ports={"input": "raw"}
    )
    out = await node()
    assert out["output"] == "raw"


# --------------------------------------------------------------------------- TypeConvert (config)


def test_type_convert_input_port_follows_conversion() -> None:
    ports_map = TypeConvert.input_ports_for_config({"conversion": "documents_to_text"})
    assert ports_map["input"].family.value == "DOCUMENTS"


def test_type_convert_input_port_defaults_when_unknown() -> None:
    # unknown conversion → HandleField default (ANY) is kept
    ports_map = TypeConvert.input_ports_for_config({"conversion": "nope"})
    assert ports_map["input"].family.value == "ANY"


def test_type_convert_output_port_follows_conversion() -> None:
    outs = TypeConvert.outputs_for_config({"conversion": "text_to_message"})
    assert outs[0].port.family.value == "MESSAGE"


def test_type_convert_output_defaults_to_any_when_unknown() -> None:
    outs = TypeConvert.outputs_for_config({"conversion": "nope"})
    assert outs[0].port.family.value == "ANY"


def test_conversions_table_shape() -> None:
    assert set(CONVERSIONS) == {
        "message_to_text",
        "text_to_message",
        "documents_to_text",
        "json_to_text",
        "text_to_json",
        "table_to_json",
        "json_to_table",
    }


async def test_type_convert_table_to_json() -> None:
    node = ComponentTestHarness().build(
        TypeConvert,
        config={"conversion": "table_to_json"},
        ports={"input": [{"a": 1}, {"a": 2}]},
    )
    out = await node()
    assert out["output"] == {"rows": [{"a": 1}, {"a": 2}]}


async def test_type_convert_json_to_table() -> None:
    node = ComponentTestHarness().build(
        TypeConvert,
        config={"conversion": "json_to_table"},
        ports={"input": {"rows": [{"a": 1}, {"a": 2}]}},
    )
    out = await node()
    assert out["output"] == [{"a": 1}, {"a": 2}]


# --------------------------------------------------------------------------- JsonExtract


async def test_json_extract_single_scalar_match() -> None:
    node = ComponentTestHarness().build(
        JsonExtract, config={"path": "$.name"}, ports={"input": {"name": "Ada"}}
    )
    out = await node()
    assert out["value"] == {"value": "Ada"}
    assert out["text"] == "Ada"


async def test_json_extract_single_dict_match() -> None:
    node = ComponentTestHarness().build(
        JsonExtract, config={"path": "$.obj"}, ports={"input": {"obj": {"k": 1}}}
    )
    out = await node()
    assert out["value"] == {"k": 1}
    assert json.loads(out["text"]) == {"k": 1}


async def test_json_extract_multiple_matches_list() -> None:
    node = ComponentTestHarness().build(
        JsonExtract, config={"path": "$.items[*]"}, ports={"input": {"items": [1, 2, 3]}}
    )
    out = await node()
    assert out["value"] == {"value": [1, 2, 3]}
    assert json.loads(out["text"]) == [1, 2, 3]


async def test_json_extract_missing_path_yields_empty_list() -> None:
    node = ComponentTestHarness().build(
        JsonExtract, config={"path": "$.missing"}, ports={"input": {"name": "Ada"}}
    )
    out = await node()
    assert out["value"] == {"value": []}


# --------------------------------------------------------------------------- Parser


async def test_parser_regex_named_groups() -> None:
    node = ComponentTestHarness().build(
        Parser,
        config={"mode": "regex", "pattern": r"(?P<year>\d{4})-(?P<month>\d{2})"},
        ports={"input": "2026-07"},
    )
    out = await node()
    assert out["json"] == {"matched": True, "year": "2026", "month": "07"}


async def test_parser_regex_unnamed_groups() -> None:
    node = ComponentTestHarness().build(
        Parser,
        config={"mode": "regex", "pattern": r"(\d+)x(\d+)"},
        ports={"input": "3x4"},
    )
    out = await node()
    assert out["json"] == {"matched": True, "1": "3", "2": "4"}


async def test_parser_regex_no_match() -> None:
    node = ComponentTestHarness().build(
        Parser, config={"mode": "regex", "pattern": r"zzz"}, ports={"input": "abc"}
    )
    out = await node()
    assert out["json"] == {"matched": False}


async def test_parser_split_mode() -> None:
    node = ComponentTestHarness().build(
        Parser, config={"mode": "split", "pattern": ","}, ports={"input": "a,b,c"}
    )
    out = await node()
    assert out["json"] == {"parts": ["a", "b", "c"]}


async def test_parser_split_empty_separator_returns_whole_text() -> None:
    node = ComponentTestHarness().build(
        Parser, config={"mode": "split", "pattern": ""}, ports={"input": "abc"}
    )
    out = await node()
    assert out["json"] == {"parts": ["abc"]}
