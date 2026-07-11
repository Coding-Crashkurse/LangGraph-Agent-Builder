"""Unit tests for the LLM Call component (lab.llm.llm_call).

Covers dynamic {var} prompt resolution (port > data), token-streaming vs
one-shot invoke, and the structured-output JSON parse (success + fallback).
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from langgraph_agent_builder.components.llm.llm_call import LLMCall, collect_prompt_values
from langgraph_agent_builder.sdk.component import BuildContext, InputBinding
from langgraph_agent_builder.sdk.ports import Message
from langgraph_agent_builder.sdk.testing import ComponentTestHarness


async def test_streams_rendered_prompt_from_connected_port() -> None:
    # echo model reflects the last human message = the rendered prompt.
    built = ComponentTestHarness().build(
        LLMCall,
        config={"prompt": "Say {greeting}", "stream_tokens": True},
        ports={"model": {"provider": "echo"}, "greeting": "hello"},
    )
    result = await built()
    assert result["text"] == "Say hello"
    assert isinstance(result["message"], Message)
    assert result["message"].content == "Say hello"
    assert result["message"].role == "assistant"
    assert isinstance(result["messages"][0], AIMessage)


async def test_prompt_var_falls_back_to_shared_data() -> None:
    # `name` has no connected port; it resolves from state["data"].
    built = ComponentTestHarness().build(
        LLMCall,
        config={"prompt": "Hi {name}"},
        ports={"model": {"provider": "echo"}},
    )
    result = await built(state={"data": {"name": "Bob"}})
    assert result["text"] == "Hi Bob"


async def test_no_stream_with_system_and_structured_json() -> None:
    built = ComponentTestHarness().build(
        LLMCall,
        config={
            "prompt": "extract",
            "system": "You are precise.",
            "stream_tokens": False,
            "structured_output": True,
            "output_schema": {"type": "object", "properties": {"a": {"type": "integer"}}},
        },
        ports={"model": {"provider": "fake", "replies": ['{"a": 7}']}},
    )
    result = await built()
    assert result["text"] == '{"a": 7}'
    assert result["json"] == {"a": 7}


async def test_structured_output_bad_json_falls_back_to_raw() -> None:
    built = ComponentTestHarness().build(
        LLMCall,
        config={
            "prompt": "extract",
            "stream_tokens": False,
            "structured_output": True,
            "output_schema": {"type": "object"},
        },
        ports={"model": {"provider": "fake", "replies": ["oops not json"]}},
    )
    result = await built()
    assert result["json"] == {"raw": "oops not json"}


def test_collect_prompt_values_prefers_port_over_data() -> None:
    ctx = BuildContext(
        node_id="n",
        input_bindings={
            "topic": InputBinding(input_name="topic", channel=None, constant="ports-topic"),
        },
    )
    state = {"data": {"topic": "data-topic", "extra": "from-data"}}
    values = collect_prompt_values(ctx, state, "About {topic} and {extra}")
    # connected constant wins for `topic`; `extra` falls through to data
    assert values == {"topic": "ports-topic", "extra": "from-data"}
