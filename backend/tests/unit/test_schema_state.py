"""Unit tests for langgraph_agent_builder.schema.state — reducers and initial_state (SPEC §5.1)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from langgraph_agent_builder.schema.state import initial_state, keep_first, merge_data, merge_keyed


def test_merge_data_last_write_wins() -> None:
    assert merge_data({"a": 1, "b": 2}, {"b": 3, "c": 4}) == {"a": 1, "b": 3, "c": 4}


def test_merge_data_handles_none_operands() -> None:
    assert merge_data(None, {"x": 1}) == {"x": 1}
    assert merge_data({"x": 1}, None) == {"x": 1}
    assert merge_data(None, None) == {}


def test_merge_keyed_merges_namespaced_channel() -> None:
    old = {"n1.out": "a"}
    new = {"n2.out": "b", "n1.out": "c"}
    assert merge_keyed(old, new) == {"n1.out": "c", "n2.out": "b"}


def test_keep_first_prefers_existing_value() -> None:
    assert keep_first({"run_id": "old"}, {"run_id": "new"}) == {"run_id": "old"}


def test_keep_first_takes_new_when_old_falsy() -> None:
    assert keep_first({}, {"run_id": "new"}) == {"run_id": "new"}
    assert keep_first(None, {"run_id": "new"}) == {"run_id": "new"}


def test_initial_state_wraps_input_text_in_human_message() -> None:
    state = initial_state(input_text="hello there")
    messages = state["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == "hello there"


def test_initial_state_keeps_existing_messages_over_input_text() -> None:
    # Branch: input_text set BUT messages already present → do not synthesize.
    existing: list[Any] = [AIMessage("prior")]
    state = initial_state(input_text="ignored", messages=existing)
    assert state["messages"] == existing
    assert len(state["messages"]) == 1


def test_initial_state_omits_data_key_when_no_data() -> None:
    state = initial_state()
    assert "data" not in state
    assert state["messages"] == []


def test_initial_state_includes_data_and_run_meta() -> None:
    files = [{"name": "f.txt"}]
    state = initial_state(
        run_id="r1",
        thread_id="t1",
        mode="a2a",
        input_text="q",
        data={"k": "v"},
        files=files,
    )
    assert state["data"] == {"k": "v"}
    meta = state["run_meta"]
    assert meta["run_id"] == "r1"
    assert meta["thread_id"] == "t1"
    assert meta["mode"] == "a2a"
    assert meta["files"] == files
