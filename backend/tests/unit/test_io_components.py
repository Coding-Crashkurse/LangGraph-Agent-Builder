"""Unit tests for the IO components (SPEC §12.1).

Covers lga.components.io.start, .end, .text_io and .set_data by driving each
NodeFn directly through the ComponentTestHarness. The emphasis is on the input
precedence branches (End), the literal/message toggle (TextInput), the jinja
rendering + blank-key skipping (SetData) and the structured-input shaping
(Start).
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from lga.components.io.end import End
from lga.components.io.set_data import SetData
from lga.components.io.start import Start
from lga.components.io.text_io import TextInput, TextOutput, WebhookInput
from lga.sdk import Component, ports
from lga.sdk.testing import BuiltNode, ComponentTestHarness


def _build(
    component: type[Component],
    config: dict[str, Any] | None = None,
    port_values: dict[str, Any] | None = None,
) -> BuiltNode:
    return ComponentTestHarness().build(component, config=config, ports=port_values)


# ----------------------------------------------------------------------- Start
async def test_start_uses_run_meta_input_text() -> None:
    node = _build(Start)
    result = await node({"run_meta": {"input_text": "hello there"}})
    message = result["message"]
    assert isinstance(message, ports.Message)
    assert message.role == "user"
    assert message.content == "hello there"
    assert result["data"] == {}
    assert result["files"] == []


async def test_start_prefers_a2a_input_dict() -> None:
    node = _build(Start)
    result = await node({"run_meta": {"input_text": "x"}, "data": {"a2a_input": {"k": "v"}}})
    assert result["data"] == {"k": "v"}


async def test_start_wraps_non_dict_structured_input() -> None:
    node = _build(Start)
    result = await node({"run_meta": {"input_text": "x", "inputs": "scalar"}})
    assert result["data"] == {"value": "scalar"}


async def test_start_falls_back_to_last_human_message() -> None:
    node = _build(Start)
    result = await node({"messages": [HumanMessage(content="hey")]})
    message = result["message"]
    assert isinstance(message, ports.Message)
    assert message.content == "hey"


async def test_start_passes_through_files() -> None:
    node = _build(Start)
    result = await node({"run_meta": {"input_text": "x", "files": [{"id": "f1"}]}})
    assert result["files"] == [{"id": "f1"}]


# ------------------------------------------------------------------------- End
async def test_end_prefers_message_over_text_and_json() -> None:
    node = _build(
        End,
        port_values={
            "message": ports.Message(role="assistant", content="M"),
            "text": "T",
            "json": {"j": 1},
        },
    )
    result = await node()
    assert isinstance(result["result"], ports.Message)
    assert result["result"].content == "M"


async def test_end_uses_text_when_no_message() -> None:
    node = _build(End, port_values={"text": "just text"})
    result = await node()
    assert result["result"] == "just text"


async def test_end_uses_json_when_no_message_or_text() -> None:
    node = _build(End, port_values={"json": {"a": 1}})
    result = await node()
    assert result["result"] == {"a": 1}


async def test_end_falls_back_to_last_ai_message() -> None:
    node = _build(End)
    result = await node({"messages": [HumanMessage(content="h"), AIMessage(content="final ai")]})
    assert isinstance(result["result"], ports.Message)
    assert result["result"].content == "final ai"


async def test_end_is_empty_string_without_any_input() -> None:
    node = _build(End)
    result = await node()
    assert result["result"] == ""


# ------------------------------------------------------------------- TextInput
async def test_text_input_emits_literal_value() -> None:
    node = _build(TextInput, config={"value": "literal"})
    result = await node()
    assert result["text"] == "literal"


async def test_text_input_uses_inbound_message_when_toggled() -> None:
    node = _build(TextInput, config={"value": "ignored", "from_message": True})
    result = await node({"messages": [HumanMessage(content="human said")]})
    assert result["text"] == "human said"


async def test_text_input_defaults_to_empty_string() -> None:
    node = _build(TextInput)
    result = await node()
    assert result["text"] == ""


# ------------------------------------------------------------------ TextOutput
async def test_text_output_returns_connected_text() -> None:
    node = _build(TextOutput, port_values={"text": "the result"})
    result = await node()
    assert result["result"] == "the result"


async def test_text_output_defaults_to_empty_string() -> None:
    node = _build(TextOutput)
    result = await node()
    assert result["result"] == ""


# ---------------------------------------------------------------- WebhookInput
async def test_webhook_input_exposes_payload() -> None:
    node = _build(WebhookInput)
    result = await node({"data": {"webhook_payload": {"event": "ping"}}})
    assert result["payload"] == {"event": "ping"}


async def test_webhook_input_defaults_to_empty_object() -> None:
    node = _build(WebhookInput)
    result = await node()
    assert result["payload"] == {}


# --------------------------------------------------------------------- SetData
async def test_set_data_renders_jinja_over_message() -> None:
    node = _build(
        SetData,
        config={"entries": [{"key": "greeting", "template": "Hi {{ message }}"}]},
    )
    result = await node({"messages": [HumanMessage(content="world")]})
    assert result["data"] == {"greeting": "Hi world"}


async def test_set_data_reads_data_and_route_variables() -> None:
    node = _build(
        SetData,
        config={
            "entries": [
                {"key": "x", "template": "{{ data.foo }}"},
                {"key": "r", "template": "{{ route.next }}"},
            ]
        },
    )
    result = await node({"data": {"foo": "bar"}, "route": {"next": "n1"}})
    assert result["data"] == {"x": "bar", "r": "n1"}


async def test_set_data_skips_blank_keys() -> None:
    node = _build(
        SetData,
        config={
            "entries": [
                {"key": "", "template": "ignored"},
                {"key": "  ", "template": "also ignored"},
                {"key": "kept", "template": "yes"},
            ]
        },
    )
    result = await node()
    assert result["data"] == {"kept": "yes"}
