"""Component.config_schema must accept the implicit tool-mode fields the form
renders (SPEC §4.2 client-side validation, §4.7 implicit fields)."""

from __future__ import annotations

import jsonschema  # type: ignore[import-untyped]  # no stubs installed for jsonschema
import pytest

from langgraph_agent_builder.sdk.registry import get_registry


def test_tool_capable_schema_accepts_implicit_fields() -> None:
    calculator = get_registry().get("lab.tools.calculator")
    assert calculator is not None
    assert calculator.tool_mode_supported
    schema = calculator.config_schema()
    assert schema["additionalProperties"] is False
    # a config the node form legitimately produces must validate
    jsonschema.validate(
        {
            "expression": "1+1",
            "tool_mode": True,
            "tool_name": "calc",
            "tool_description": "adds numbers",
        },
        schema,
    )


def test_non_tool_component_schema_rejects_tool_fields() -> None:
    start = get_registry().get("lab.io.start")
    assert start is not None
    assert not start.tool_mode_supported
    schema = start.config_schema()
    assert "tool_mode" not in schema["properties"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"tool_mode": True}, schema)


def test_implicit_fields_derived_from_one_source() -> None:
    calculator = get_registry().get("lab.tools.calculator")
    assert calculator is not None
    names = [f.name for f in calculator._implicit_field_objects()]
    assert names == ["tool_mode", "tool_name", "tool_description"]
    assert [d["name"] for d in calculator._implicit_fields()] == names
