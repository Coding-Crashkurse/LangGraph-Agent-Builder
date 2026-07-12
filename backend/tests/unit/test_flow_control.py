"""Unit tests for the interrupt-based Human flow-control components (SPEC §5.5).

The Human components need the real interrupt/resume machinery and so run through
a compiler + in-memory Executor. The focus is the approval decision parsing
(dict / string / invalid → reject), the comment-append branch, and the preview
toggle. Router/Loop branching is covered by ``test_new_palette_nodes``.
"""

from __future__ import annotations

from typing import Any

import pytest

from langgraph_agent_builder.compiler import compile_flow
from langgraph_agent_builder.runtime.executor import Executor
from langgraph_agent_builder.runtime.streams import EventBus


# ----------------------------------------------------- Human components (interrupt)
@pytest.fixture
def executor() -> Executor:
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()

    async def _get() -> InMemorySaver:
        return saver

    return Executor(checkpointer_getter=_get, bus=EventBus())


def _node(node_id: str, component_id: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "component_id": component_id,
        "component_version": "1.0.0",
        "config": config,
        "position": {"x": 0, "y": 0},
    }


def _edge(edge_id: str, kind: str, src: str, out: str, dst: str, inp: str) -> dict[str, Any]:
    return {
        "id": edge_id,
        "kind": kind,
        "source": {"node": src, "output": out},
        "target": {"node": dst, "input": inp},
    }


def _approval_spec(review_config: dict[str, Any]) -> dict[str, Any]:
    """start → review; approve → echo → end, reject → end.

    The echo node re-emits the last human message, so an appended reviewer
    comment surfaces as the terminal text — making the append_comment branch
    observable. The reject branch reaches the terminal with no wired value, so
    the flow result falls back to empty.
    """
    return {
        "schema_version": "1",
        "flow": {"name": "hitl-a", "slug": "hitl-a", "description": "x"},
        "nodes": [
            _node("start", "lab.io.start", {}),
            _node("review", "lab.flow.human_approval", review_config),
            _node("echo", "lab.testing.echo_llm", {}),
            _node("end", "lab.io.end", {}),
        ],
        "edges": [
            _edge("e1", "data", "start", "message", "review", "input"),
            _edge("e2", "router", "review", "approve", "echo", "input"),
            _edge("e3", "data", "echo", "text", "end", "result"),
            _edge("e4", "router", "review", "reject", "end", "result"),
        ],
    }


def _input_spec(node_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "flow": {"name": "hitl-i", "slug": "hitl-i", "description": "x"},
        "nodes": [
            _node("start", "lab.io.start", {}),
            _node("ask", "lab.flow.human_input", node_config),
            _node("end", "lab.io.end", {}),
        ],
        "edges": [
            _edge("e1", "data", "start", "message", "ask", "input"),
            _edge("e2", "data", "ask", "message", "end", "result"),
        ],
    }


async def test_human_approval_interrupt_carries_prompt_and_preview(
    executor: Executor,
) -> None:
    compiled = compile_flow(_approval_spec({"prompt": "Ship it?"}), use_cache=False)
    assert compiled.ok, [d.message for d in compiled.diagnostics]
    result = await executor.execute(compiled, input_text="hello", thread_id="a1")
    assert result.status == "input_required"
    assert result.interrupt is not None
    assert result.interrupt["kind"] == "approval"
    assert result.interrupt["prompt"] == "Ship it?"
    # include_preview defaults to True → last message text is attached
    assert result.interrupt["context"]["preview"] == "hello"


async def test_human_approval_appends_reviewer_comment(executor: Executor) -> None:
    compiled = compile_flow(
        _approval_spec({"prompt": "p", "append_comment": True}), use_cache=False
    )
    await executor.execute(compiled, input_text="hello", thread_id="a2")
    resumed = await executor.execute(
        compiled, thread_id="a2", resume={"decision": "approve", "comment": "redo"}
    )
    assert resumed.status == "completed"
    # the echo terminal re-emitted the appended reviewer message
    assert resumed.result_text == "[reviewer] redo"


async def test_human_approval_without_append_comment_keeps_original(
    executor: Executor,
) -> None:
    compiled = compile_flow(
        _approval_spec({"prompt": "p", "append_comment": False}), use_cache=False
    )
    await executor.execute(compiled, input_text="hello", thread_id="a3")
    resumed = await executor.execute(
        compiled, thread_id="a3", resume={"decision": "approve", "comment": "redo"}
    )
    assert resumed.status == "completed"
    # no reviewer message appended → echo falls back to the original user text
    assert resumed.result_text == "hello"


async def test_human_approval_accepts_plain_string_resume(executor: Executor) -> None:
    compiled = compile_flow(_approval_spec({"prompt": "p"}), use_cache=False)
    await executor.execute(compiled, input_text="hello", thread_id="a4")
    resumed = await executor.execute(compiled, thread_id="a4", resume="approve")
    assert resumed.status == "completed"
    assert resumed.result_text == "hello"


async def test_human_approval_invalid_decision_is_rejected(executor: Executor) -> None:
    compiled = compile_flow(_approval_spec({"prompt": "p"}), use_cache=False)
    await executor.execute(compiled, input_text="hello", thread_id="a5")
    resumed = await executor.execute(compiled, thread_id="a5", resume={"decision": "maybe-later"})
    # unparseable decision → reject branch → routes to the terminal
    assert resumed.status == "completed"
    assert resumed.result_text == ""


async def test_human_approval_no_preview_when_disabled(executor: Executor) -> None:
    compiled = compile_flow(
        _approval_spec({"prompt": "p", "include_preview": False}), use_cache=False
    )
    result = await executor.execute(compiled, input_text="hello", thread_id="a6")
    assert result.status == "input_required"
    assert result.interrupt is not None
    assert result.interrupt["context"] == {}


async def test_human_input_returns_free_text(executor: Executor) -> None:
    compiled = compile_flow(_input_spec({"prompt": "Name?"}), use_cache=False)
    first = await executor.execute(compiled, input_text="hi", thread_id="i1")
    assert first.status == "input_required"
    assert first.interrupt is not None
    assert first.interrupt["kind"] == "free_text"
    resumed = await executor.execute(compiled, thread_id="i1", resume={"text": "typed answer"})
    assert resumed.status == "completed"
    assert resumed.result_text == "typed answer"


async def test_human_input_serialises_structured_resume(executor: Executor) -> None:
    compiled = compile_flow(
        _input_spec({"prompt": "Data?", "input_schema": {"type": "object"}}),
        use_cache=False,
    )
    await executor.execute(compiled, input_text="hi", thread_id="i2")
    resumed = await executor.execute(compiled, thread_id="i2", resume={"a": 1})
    assert resumed.status == "completed"
    assert resumed.result_text == '{"a": 1}'


async def test_human_input_stringifies_scalar_resume(executor: Executor) -> None:
    compiled = compile_flow(_input_spec({"prompt": "Name?"}), use_cache=False)
    await executor.execute(compiled, input_text="hi", thread_id="i3")
    resumed = await executor.execute(compiled, thread_id="i3", resume="plain answer")
    assert resumed.status == "completed"
    assert resumed.result_text == "plain answer"
