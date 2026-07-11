"""Unit tests for the flow-control components (SPEC §5.5, §12.3).

Routers and Loop Until are driven directly through the ComponentTestHarness;
the interrupt-based Human components need the real interrupt/resume machinery
and so run through a compiler + in-memory Executor. The focus is the branchy
error paths: broken predicates, no-match fallbacks, counter guards, and the
approval decision parsing (dict / string / invalid → reject).
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from langgraph_agent_builder.compiler import compile_flow
from langgraph_agent_builder.components.flow_control.loop_until import LoopUntil
from langgraph_agent_builder.components.flow_control.routers import LLMRouter, RuleRouter
from langgraph_agent_builder.runtime.executor import Executor
from langgraph_agent_builder.runtime.streams import EventBus
from langgraph_agent_builder.sdk import Component
from langgraph_agent_builder.sdk.testing import BuiltNode, ComponentTestHarness


def _build(
    component: type[Component],
    config: dict[str, Any] | None = None,
    port_values: dict[str, Any] | None = None,
) -> BuiltNode:
    return ComponentTestHarness().build(component, config=config, ports=port_values)


def _state_with_message(text: str) -> dict[str, Any]:
    return {"messages": [HumanMessage(content=text)]}


# ------------------------------------------------------------------- LoopUntil
async def test_loop_until_continues_and_counts_first_iteration() -> None:
    node = _build(LoopUntil, config={"max_iterations": 5})
    result = await node()
    assert result["route"] == "continue"
    assert result["data"] == {"__loop_under_test": 1}


async def test_loop_until_stops_when_max_iterations_exceeded() -> None:
    node = _build(LoopUntil, config={"max_iterations": 3})
    result = await node({"data": {"__loop_under_test": 3}})
    assert result["route"] == "done"
    assert result["data"] == {"__loop_under_test": 4}


async def test_loop_until_done_when_condition_holds() -> None:
    node = _build(
        LoopUntil,
        config={"condition": '"APPROVED" in message', "max_iterations": 10},
    )
    result = await node(_state_with_message("APPROVED now"))
    assert result["route"] == "done"


async def test_loop_until_continues_when_condition_false() -> None:
    node = _build(
        LoopUntil,
        config={"condition": '"APPROVED" in message', "max_iterations": 10},
    )
    result = await node(_state_with_message("not yet"))
    assert result["route"] == "continue"


async def test_loop_until_broken_condition_continues() -> None:
    node = _build(LoopUntil, config={"condition": "1 / 0", "max_iterations": 10})
    result = await node()
    assert result["route"] == "continue"


# ------------------------------------------------------------------- LLMRouter
async def test_llm_router_keyword_match_without_model() -> None:
    node = _build(LLMRouter, config={"labels": ["refund", "other"]})
    result = await node(_state_with_message("I want a refund"))
    assert result["route"] == "refund"


async def test_llm_router_no_match_falls_to_last_label() -> None:
    node = _build(LLMRouter, config={"labels": ["refund", "other"]})
    result = await node(_state_with_message("hello there"))
    assert result["route"] == "other"


async def test_llm_router_uses_model_when_connected() -> None:
    node = _build(
        LLMRouter,
        config={"labels": ["refund", "other"]},
        port_values={"model": {"provider": "fake", "replies": ["refund"]}},
    )
    result = await node(_state_with_message("ambiguous text"))
    assert result["route"] == "refund"


async def test_llm_router_empty_labels_routes_to_empty_string() -> None:
    node = _build(LLMRouter, config={"labels": []})
    result = await node(_state_with_message("x"))
    assert result["route"] == ""


# ------------------------------------------------------------------ RuleRouter
def test_rule_router_outputs_dedup_and_append_default() -> None:
    outs = RuleRouter.outputs_for_config(
        {
            "rules": [{"label": "a"}, {"label": "a"}, {"label": "b"}],
            "default_label": "fallback",
        }
    )
    assert [o.name for o in outs] == ["a", "b", "fallback"]


def test_rule_router_outputs_skip_default_already_declared() -> None:
    outs = RuleRouter.outputs_for_config({"rules": [{"label": "a"}], "default_label": "a"})
    assert [o.name for o in outs] == ["a"]


async def test_rule_router_first_matching_rule_wins() -> None:
    node = _build(
        RuleRouter,
        config={
            "rules": [
                {"label": "refund", "when": '"refund" in message'},
                {"label": "greet", "when": '"hi" in message'},
            ],
            "default_label": "default",
        },
    )
    result = await node(_state_with_message("refund please"))
    assert result["route"] == "refund"


async def test_rule_router_falls_back_to_default() -> None:
    node = _build(
        RuleRouter,
        config={
            "rules": [{"label": "refund", "when": '"refund" in message'}],
            "default_label": "default",
        },
    )
    result = await node(_state_with_message("hello"))
    assert result["route"] == "default"


async def test_rule_router_skips_broken_predicate() -> None:
    node = _build(
        RuleRouter,
        config={
            "rules": [
                {"label": "boom", "when": "1 / 0"},
                {"label": "ok", "when": '"yes" in message'},
            ],
            "default_label": "default",
        },
    )
    result = await node(_state_with_message("yes indeed"))
    assert result["route"] == "ok"


async def test_rule_router_skips_rows_missing_label_or_predicate() -> None:
    node = _build(
        RuleRouter,
        config={
            "rules": [
                {"label": "", "when": '"x" in message'},
                {"label": "nowhen", "when": ""},
            ],
            "default_label": "default",
        },
    )
    result = await node(_state_with_message("x"))
    assert result["route"] == "default"


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
    """start → review; approve → echo → text_output, reject → text_output.

    The echo node re-emits the last human message, so an appended reviewer
    comment surfaces as the terminal text — making the append_comment branch
    observable.
    """
    return {
        "schema_version": "1",
        "flow": {"name": "hitl-a", "slug": "hitl-a", "description": "x"},
        "nodes": [
            _node("start", "lab.io.start", {}),
            _node("review", "lab.flow.human_approval", review_config),
            _node("echo", "lab.testing.echo_llm", {}),
            _node("out", "lab.io.text_output", {}),
            _node("rej", "lab.io.text_output", {}),
        ],
        "edges": [
            _edge("e1", "data", "start", "message", "review", "input"),
            _edge("e2", "router", "review", "approve", "echo", "input"),
            _edge("e3", "data", "echo", "text", "out", "text"),
            _edge("e4", "router", "review", "reject", "rej", "text"),
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
            _edge("e2", "data", "ask", "message", "end", "message"),
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
    # unparseable decision → reject branch → routes to the rejection terminal
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
