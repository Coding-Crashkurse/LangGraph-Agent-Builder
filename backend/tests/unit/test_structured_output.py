"""Unit tests for the Structured Output component (lga.llm.structured_output).

Drives a deterministic "fake" model whose scripted reply is parsed into the
`json` / `table` outputs, exercising fence-stripping, list vs object shaping,
and the JSON-decode error fallback.
"""

from __future__ import annotations

from typing import Any

from lga.components.llm.structured_output import StructuredOutput
from lga.sdk.ports import Message
from lga.sdk.testing import ComponentTestHarness


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
