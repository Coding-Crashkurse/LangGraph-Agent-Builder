"""Component.config_schema must accept the implicit tool-mode fields the form
renders (SPEC §4.2 client-side validation, §4.7 implicit fields)."""

from __future__ import annotations

import jsonschema  # type: ignore[import-untyped]  # no stubs installed for jsonschema
import pytest

from langgraph_agent_builder.sdk.registry import get_registry


def test_tool_capable_schema_accepts_implicit_fields() -> None:
    http_request = get_registry().get("lab.tools.http_request")
    assert http_request is not None
    assert http_request.tool_mode_supported
    schema = http_request.config_schema()
    assert schema["additionalProperties"] is False
    # a config the node form legitimately produces must validate
    jsonschema.validate(
        {
            "url": "https://example.com",
            "tool_mode": True,
            "tool_name": "fetch",
            "tool_description": "fetches a URL",
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
    http_request = get_registry().get("lab.tools.http_request")
    assert http_request is not None
    names = [f.name for f in http_request._implicit_field_objects()]
    assert names == ["tool_mode", "tool_name", "tool_description"]
    assert [d["name"] for d in http_request._implicit_fields()] == names
