"""Unit tests for the Structured Output component (lab.llm.structured_output).

Drives a deterministic "fake" model whose scripted reply is parsed into the
`json` / `table` outputs, exercising fence-stripping, list vs object shaping,
and the JSON-decode error fallback.
"""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.components.llm.structured_output import StructuredOutput
from langgraph_agent_builder.sdk.ports import Message
from langgraph_agent_builder.sdk.testing import ComponentTestHarness


async def _run(
    reply: str,
    *,
    config: dict[str, Any] | None = None,
    input_value: Any = None,
) -> dict[str, Any]:
    ports: dict[str, Any] = {"model": {"provider": "fake", "replies": [reply]}}
    if input_value is not None:
        ports["input"] = input_value
    built = ComponentTestHarness().build(
        StructuredOutput,
        config={"output_schema": {"type": "object"}, **(config or {})},
        ports=ports,
    )
    return await built()


async def test_object_reply_wraps_single_row_table() -> None:
    result = await _run(
        '{"name": "ada"}',
        config={"instructions": "Extract the person."},
        input_value=Message(role="user", content="Ada Lovelace"),
    )
    assert result["json"] == {"name": "ada"}
    # a bare object becomes a one-row table
    assert result["table"] == [{"name": "ada"}]


async def test_json_code_fence_is_stripped() -> None:
    result = await _run('```json\n{"a": 1}\n```')
    assert result["json"] == {"a": 1}


async def test_bare_code_fence_with_list_payload() -> None:
    result = await _run('```\n[{"a": 1}, {"a": 2}]\n```')
    assert result["json"] == [{"a": 1}, {"a": 2}]
    assert result["table"] == [{"a": 1}, {"a": 2}]


async def test_rows_key_becomes_table() -> None:
    result = await _run('{"rows": [{"x": 1}, {"x": 2}]}')
    assert result["json"] == {"rows": [{"x": 1}, {"x": 2}]}
    assert result["table"] == [{"x": 1}, {"x": 2}]


async def test_invalid_json_falls_back_to_raw() -> None:
    result = await _run("this is not json")
    assert result["json"] == {"raw": "this is not json"}
    assert result["table"] == [{"raw": "this is not json"}]


async def test_missing_input_uses_empty_text_and_default_schema() -> None:
    # No `input` port and no instructions → default prompt path, empty text.
    built = ComponentTestHarness().build(
        StructuredOutput,
        config={},  # output_schema falls back to {"type": "object"}
        ports={"model": {"provider": "fake", "replies": ['{"ok": true}']}},
    )
    result = await built()
    assert result["json"] == {"ok": True}
    assert result["table"] == [{"ok": True}]


# --------------------------------------------------------------- TableInput schema editor
async def test_row_based_schema_editor_runs() -> None:
    result = await _run(
        '{"name": "ada", "age": 36}',
        config={
            "output_schema": [
                {"name": "name", "description": "person name", "type": "str"},
                {"name": "age", "type": "int"},
            ]
        },
        input_value=Message(role="user", content="Ada, 36"),
    )
    assert result["json"] == {"name": "ada", "age": 36}


def test_rows_to_schema_shapes_json_schema() -> None:
    from langgraph_agent_builder.components.llm.structured_output import _rows_to_schema

    schema = _rows_to_schema(
        [
            {"name": "name", "description": "d", "type": "str"},
            {"name": "n", "type": "int"},
            {"name": "", "type": "bool"},  # nameless rows are skipped
        ]
    )
    assert schema == {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "d"}, "n": {"type": "integer"}},
        "required": ["name", "n"],
    }
    assert _rows_to_schema([]) == {"type": "object"}


def test_migrate_config_converts_legacy_json_schema_to_rows() -> None:
    migrated = StructuredOutput.migrate_config(
        "1.0.0",
        {
            "output_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "person name"},
                    "age": {"type": "integer"},
                },
            }
        },
    )
    assert migrated["output_schema"] == [
        {"name": "name", "description": "person name", "type": "str"},
        {"name": "age", "description": "", "type": "int"},
    ]
