"""Unit tests for sdk.runtime (RunContext emitters, cancel, config lookup, SPEC §4.1).

Emit paths are exercised through a *real* LangGraph custom stream rather than
mocks: langgraph provides the stream writer, so RunContext._emit round-trips
into observable stream chunks.
"""

from __future__ import annotations

import asyncio

import pytest
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from langgraph_agent_builder.sdk.runtime import (
    RUN_CTX_KEY,
    RunContext,
    current_node_id,
    get_run_context,
)


class _S(TypedDict):
    x: int


def _emit_graph() -> object:
    def node(state: _S) -> _S:
        token = current_node_id.set("nodeA")
        try:
            ctx = RunContext()
            ctx.emit_status("working")
            ctx.emit_log("info", "hello")
            ctx.stream_writer("tok")
            ctx.emit("custom", {"a": 1})
        finally:
            current_node_id.reset(token)
        return {"x": state["x"] + 1}

    return (
        StateGraph(_S)
        .add_node("node", node)
        .add_edge(START, "node")
        .add_edge("node", END)
        .compile()
    )


def test_emitters_stream_into_custom_chunks() -> None:
    graph = _emit_graph()
    chunks = list(graph.stream({"x": 0}, stream_mode="custom"))  # type: ignore[attr-defined]
    assert chunks == [
        {"event": "node_status", "node_id": "nodeA", "data": {"text": "working"}},
        {"event": "node_log", "node_id": "nodeA", "data": {"level": "info", "msg": "hello"}},
        {"event": "node_token", "node_id": "nodeA", "data": {"delta": "tok"}},
        {"event": "custom", "node_id": "nodeA", "data": {"a": 1}},
    ]


def test_emit_outside_stream_is_noop() -> None:
    # No runnable context → get_stream_writer raises → _stream_write swallows it.
    # The call must not raise and must produce no side effect.
    RunContext().emit_status("nowhere")


def test_noop_context_emits_nothing_even_in_stream() -> None:
    def node(state: _S) -> _S:
        RunContext(_noop=True).emit_status("suppressed")
        return {"x": state["x"] + 1}

    graph = (
        StateGraph(_S)
        .add_node("node", node)
        .add_edge(START, "node")
        .add_edge("node", END)
        .compile()
    )
    chunks = list(graph.stream({"x": 0}, stream_mode="custom"))
    assert chunks == []


def test_cancelled_property_reflects_event() -> None:
    ctx = RunContext()
    assert ctx.cancelled is False
    ctx.cancellation.set()
    assert ctx.cancelled is True


def test_raise_if_cancelled_no_raise_when_clear() -> None:
    RunContext().raise_if_cancelled()  # must not raise


def test_raise_if_cancelled_raises_when_set() -> None:
    ctx = RunContext()
    ctx.cancellation.set()
    with pytest.raises(asyncio.CancelledError):
        ctx.raise_if_cancelled()


def test_run_context_field_defaults() -> None:
    ctx = RunContext()
    assert ctx.run_id == ""
    assert ctx.thread_id == ""
    assert ctx.attempt == 1
    assert ctx.mode == "api"
    assert isinstance(ctx.cancellation, asyncio.Event)


def test_get_run_context_returns_stored_context() -> None:
    ctx = RunContext(run_id="r1")
    config = {"configurable": {RUN_CTX_KEY: ctx}}
    assert get_run_context(config) is ctx


def test_get_run_context_missing_key_returns_noop() -> None:
    result = get_run_context({"configurable": {}})
    assert result._noop is True
    assert result is not RunContext(run_id="r1")


def test_get_run_context_non_dict_config_returns_noop() -> None:
    assert get_run_context("not-a-config")._noop is True


def test_get_run_context_wrong_type_value_returns_noop() -> None:
    config = {"configurable": {RUN_CTX_KEY: "not-a-run-context"}}
    assert get_run_context(config)._noop is True


def test_noop_singleton_shared() -> None:
    # every degraded lookup returns the same shared no-op instance
    a = get_run_context({})
    b = get_run_context("x")
    assert a is b
    assert a._noop is True
