"""Unit tests for the zero-dependency testing components (SPEC §12.7).

Covers langgraph_agent_builder.components.testing.echo_llm, .mock and .slow_node by exercising each
NodeFn in isolation through the ComponentTestHarness. Error paths (cancellation,
configured failure) and the message-fallback branches are the focus.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from langgraph_agent_builder.components.testing.echo_llm import EchoLLM
from langgraph_agent_builder.components.testing.mock import _LOREM, FakeEmbeddings, MockData
from langgraph_agent_builder.components.testing.slow_node import EchoData, FailingNode, SlowNode
from langgraph_agent_builder.sdk import Component, ports
from langgraph_agent_builder.sdk.runtime import RUN_CTX_KEY, RunContext
from langgraph_agent_builder.sdk.testing import BuiltNode, ComponentTestHarness


def _build(
    component: type[Component],
    config: dict[str, Any] | None = None,
    port_values: dict[str, Any] | None = None,
) -> BuiltNode:
    return ComponentTestHarness().build(component, config=config, ports=port_values)


# --------------------------------------------------------------------- EchoLLM
async def test_echo_prefixes_message_port() -> None:
    node = _build(
        EchoLLM,
        config={"prefix": ">> "},
        port_values={"input": ports.Message(role="user", content="hello")},
    )
    result = await node()
    assert result["text"] == ">> hello"
    message = result["message"]
    assert isinstance(message, ports.Message)
    assert message.role == "assistant"
    assert message.content == ">> hello"
    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == ">> hello"


async def test_echo_uppercase_transforms_text() -> None:
    node = _build(
        EchoLLM,
        config={"uppercase": True},
        port_values={"input": ports.Message(role="user", content="abc")},
    )
    result = await node()
    assert result["text"] == "ABC"


async def test_echo_falls_back_to_last_human_message() -> None:
    node = _build(EchoLLM)
    state = {"messages": [AIMessage(content="ignored"), HumanMessage(content="from human")]}
    result = await node(state)
    assert result["text"] == "from human"


async def test_echo_falls_back_to_last_message_when_no_human() -> None:
    node = _build(EchoLLM)
    state = {"messages": [AIMessage(content="ai only")]}
    result = await node(state)
    assert result["text"] == "ai only"


# ---------------------------------------------------------------- FakeEmbeddings
async def test_fake_embeddings_default_dimension() -> None:
    node = _build(FakeEmbeddings)
    result = await node()
    assert result["embedding"] == {"provider": "fake", "dim": 32}


async def test_fake_embeddings_honours_configured_dimension() -> None:
    node = _build(FakeEmbeddings, config={"dim": 8})
    result = await node()
    assert result["embedding"] == {"provider": "fake", "dim": 8}


# -------------------------------------------------------------------- MockData
async def test_mock_data_emits_requested_row_count_and_shapes() -> None:
    node = _build(MockData, config={"rows": 3})
    result = await node()
    table = result["table"]
    assert len(table) == 3
    assert table[0] == {"id": 0, "name": "Item 0", "value": 0, "active": True}
    assert table[1]["value"] == 7
    assert table[1]["active"] is False
    assert result["json"] == {"lorem": _LOREM, "count": 3}
    message = result["message"]
    assert isinstance(message, ports.Message)
    assert message.role == "assistant"
    assert message.content == _LOREM


async def test_mock_data_defaults_to_fifty_rows() -> None:
    node = _build(MockData)
    result = await node()
    assert len(result["table"]) == 50
    assert result["json"]["count"] == 50


# -------------------------------------------------------------------- SlowNode
async def test_slow_node_passes_through_message_after_sleeping() -> None:
    node = _build(
        SlowNode,
        config={"seconds": 0.1},
        port_values={"input": ports.Message(role="assistant", content="carry")},
    )
    result = await node()
    message = result["message"]
    assert isinstance(message, ports.Message)
    assert message.content == "carry"
    assert result["data"] == {"slept": 0.1}


async def test_slow_node_synthesises_message_without_input() -> None:
    node = _build(SlowNode, config={"seconds": 0.0})
    result = await node()
    message = result["message"]
    assert isinstance(message, ports.Message)
    assert message.content == "slept 0.0s"
    assert result["data"] == {"slept": 0.0}


async def test_slow_node_raises_when_cancelled() -> None:
    run_ctx = RunContext()
    run_ctx.cancellation.set()
    node = _build(SlowNode, config={"seconds": 5.0})
    config = {"configurable": {RUN_CTX_KEY: run_ctx}}
    with pytest.raises(asyncio.CancelledError):
        await node(state={}, config=config)


# ------------------------------------------------------------------ FailingNode
async def test_failing_node_raises_configured_error() -> None:
    node = _build(FailingNode, config={"fail": True, "error_message": "boom"})
    with pytest.raises(RuntimeError, match="boom"):
        await node()


async def test_failing_node_returns_message_when_disabled() -> None:
    node = _build(FailingNode, config={"fail": False})
    result = await node()
    message = result["message"]
    assert isinstance(message, ports.Message)
    assert message.content == "did not fail"


# --------------------------------------------------------------------- EchoData
async def test_echo_data_echoes_json_input() -> None:
    node = _build(EchoData, port_values={"input": {"k": "v"}})
    result = await node()
    assert result["json"] == {"k": "v"}
    assert result["data"] == {"echo": {"k": "v"}}


async def test_echo_data_defaults_to_empty_object() -> None:
    node = _build(EchoData)
    result = await node()
    assert result["json"] == {}
    assert result["data"] == {"echo": {}}
