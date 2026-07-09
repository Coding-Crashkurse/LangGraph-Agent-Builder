"""Unit tests for the LLM Agent component (lga.llm.llm_agent).

Exercises the reachable branches of the explicit tool-calling loop: the
no-tools single turn, RAG document injection (object + dict docs), the
graceful degrade when a model cannot bind tools, and cooperative cancellation.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool

from lga.components.llm.llm_agent import LLMAgent
from lga.sdk.ports import Document, Message, ToolDef
from lga.sdk.runtime import RUN_CTX_KEY, RunContext
from lga.sdk.testing import ComponentTestHarness


async def test_no_tools_single_turn_echoes_conversation() -> None:
    built = ComponentTestHarness().build(
        LLMAgent,
        config={"system_prompt": "You are helpful."},
        ports={"model": {"provider": "echo"}},
    )
    result = await built(state={"messages": [HumanMessage(content="hello agent")]})
    assert isinstance(result["message"], Message)
    assert result["message"].role == "assistant"
    assert result["message"].content == "hello agent"
    # one model turn → exactly one new AIMessage recorded
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], AIMessage)


async def test_injects_documents_into_system_prompt() -> None:
    # Mixed doc shapes (object with source, dict with source, object w/o source)
    # must all be consumed without error; the model still returns its answer.
    docs = [
        Document(page_content="doc one", metadata={"source": "a.txt"}),
        {"page_content": "doc two", "metadata": {"source": "b.txt"}},
        Document(page_content="doc three"),
    ]
    built = ComponentTestHarness().build(
        LLMAgent,
        config={"use_documents": True},
        ports={
            "model": {"provider": "fake", "replies": ["grounded answer"]},
            "documents": docs,
        },
    )
    result = await built(state={"messages": [HumanMessage(content="q")]})
    assert result["message"].content == "grounded answer"


async def test_use_documents_with_no_documents_skips_injection() -> None:
    built = ComponentTestHarness().build(
        LLMAgent,
        config={"use_documents": True},
        ports={"model": {"provider": "echo"}},
    )
    result = await built(state={"messages": [HumanMessage(content="just echo")]})
    assert result["message"].content == "just echo"


async def test_tools_attached_but_model_cannot_bind() -> None:
    def _echo_tool(text: str) -> str:
        return text

    tool = StructuredTool.from_function(
        func=_echo_tool, name="echo_tool", description="Echo the input."
    )
    built = ComponentTestHarness().build(
        LLMAgent,
        config={},
        ports={"model": {"provider": "fake", "replies": ["answer without tools"]}},
        tools=[ToolDef(name="echo_tool", description="Echo", callable_ref=tool)],
    )
    # FakeListChatModel.bind_tools raises NotImplementedError → warning path,
    # then the loop runs to completion with the (unbound) model.
    result = await built(state={"messages": [HumanMessage(content="hi")]})
    assert result["message"].content == "answer without tools"


async def test_cancellation_raises_before_model_call() -> None:
    rc = RunContext(mode="api")
    rc.cancellation.set()
    built = ComponentTestHarness().build(
        LLMAgent,
        config={},
        ports={"model": {"provider": "echo"}},
    )
    config: dict[str, Any] = {"configurable": {RUN_CTX_KEY: rc}}
    with pytest.raises(asyncio.CancelledError):
        await built(state={"messages": [HumanMessage(content="hi")]}, config=config)


async def test_empty_conversation_yields_empty_answer() -> None:
    # No prior messages → echo produces empty text; still a well-formed result.
    built = ComponentTestHarness().build(
        LLMAgent,
        config={},
        ports={"model": {"provider": "echo"}},
    )
    result = await built(state={})
    assert result["message"].content == ""
    assert result["message"].role == "assistant"
