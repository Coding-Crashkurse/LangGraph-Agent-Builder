"""Field serialization + descriptor rendering (SPEC §15.1, §4.2)."""

from __future__ import annotations

import pytest

from lga.sdk import fields
from lga.sdk.fields import FIELD_TYPES
from lga.sdk.ports import TEXT


def test_all_spec_field_types_exist():
    expected = {
        "StrInput",
        "MultilineInput",
        "IntInput",
        "FloatInput",
        "BoolInput",
        "SliderInput",
        "DropdownInput",
        "MultiselectInput",
        "TabInput",
        "SecretInput",
        "MultilineSecretInput",
        "DictInput",
        "NestedDictInput",
        "TableInput",
        "FileInput",
        "CodeInput",
        "PromptInput",
        "ModelInput",
        "QueryInput",
        "LinkInput",
        "McpInput",
        "HandleField",
        "ToolsInput",
    }
    assert expected <= set(FIELD_TYPES)


def test_descriptor_carries_type_and_common_attrs():
    f = fields.IntInput(name="k", min=1, max=50, default=4, info="top k")
    d = f.descriptor()
    assert d["type"] == "IntInput"
    assert d["name"] == "k" and d["display_name"] == "K"
    assert d["min"] == 1 and d["max"] == 50
    assert d["advanced"] is False and d["tool_mode"] is False


def test_json_schema_fragments():
    assert fields.IntInput(name="n", min=0, max=9).json_schema() == {
        "type": "integer",
        "minimum": 0,
        "maximum": 9,
    }
    assert fields.BoolInput(name="b").json_schema() == {"type": "boolean"}
    assert fields.DropdownInput(name="d", options=["a", "b"]).json_schema() == {
        "type": "string",
        "enum": ["a", "b"],
    }
    # combobox drops the enum (custom values allowed)
    assert "enum" not in fields.DropdownInput(name="d", options=["a"], combobox=True).json_schema()
    ms = fields.MultiselectInput(name="m", options=["x"]).json_schema()
    assert ms["type"] == "array" and ms["items"]["enum"] == ["x"]


def test_secret_input_schema_allows_refs():
    schema = fields.SecretInput(name="s").json_schema()
    assert any("$secret" in str(alt) for alt in schema["anyOf"])


def test_tab_input_max_five():
    with pytest.raises(ValueError):
        fields.TabInput(name="t", options=["1", "2", "3", "4", "5", "6"])


def test_handle_field_requires_port():
    with pytest.raises(ValueError):
        fields.HandleField(name="h")
    f = fields.HandleField(name="h", as_port=TEXT)
    assert f.port_only and f.as_port is TEXT


def test_tools_input_defaults_to_toolset_port():
    f = fields.ToolsInput(name="tools")
    assert f.as_port is not None and f.as_port.family.value == "TOOLSET"


def test_query_input_tool_mode_default():
    assert fields.QueryInput(name="q").tool_mode is True


def test_table_input_schema():
    f = fields.TableInput(
        name="rows",
        columns=[fields.ColumnSpec(name="label"), fields.ColumnSpec(name="n", type="int")],
    )
    schema = f.json_schema()
    assert schema["items"]["properties"]["label"] == {"type": "string"}
    assert schema["items"]["properties"]["n"] == {"type": "integer"}
