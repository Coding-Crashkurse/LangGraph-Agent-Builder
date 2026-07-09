"""Unit tests for lga.sdk.templating (sandboxed jinja + message/prompt helpers)."""

from __future__ import annotations

from typing import Any

import pytest
from jinja2.exceptions import SecurityError, UndefinedError

from lga.sdk.ports import Message
from lga.sdk.templating import (
    eval_predicate,
    last_message_text,
    message_text,
    render_jinja,
    render_prompt,
)


def test_message_text_none_is_empty() -> None:
    assert message_text(None) == ""


def test_message_text_plain_str() -> None:
    assert message_text("hello") == "hello"


def test_message_text_lga_message() -> None:
    assert message_text(Message(role="assistant", content="hi there")) == "hi there"


def test_message_text_langchain_str_content() -> None:
    from langchain_core.messages import AIMessage

    assert message_text(AIMessage(content="answer")) == "answer"


def test_message_text_content_blocks_joined() -> None:
    class Blocky:
        content = [
            "raw-string-block",
            {"type": "text", "text": "typed-block"},
            {"type": "image", "url": "x"},  # non-text block dropped
            {"type": "text"},  # missing text → empty
        ]

    assert message_text(Blocky()) == "raw-string-blocktyped-block"


def test_message_text_fallback_str() -> None:
    assert message_text(42) == "42"


def test_last_message_text_empty_state() -> None:
    assert last_message_text({}) == ""
    assert last_message_text({"messages": []}) == ""


def test_last_message_text_returns_last() -> None:
    state = {"messages": [Message(content="first"), Message(content="second")]}
    assert last_message_text(state) == "second"


def test_last_message_text_human_only_filter() -> None:
    from langchain_core.messages import AIMessage, HumanMessage

    state: dict[str, Any] = {
        "messages": [
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
        ]
    }
    assert last_message_text(state, human_only=True) == "q2"
    # unfiltered picks the AI message last
    assert last_message_text(state) == "q2"


def test_last_message_text_human_only_none_present() -> None:
    from langchain_core.messages import AIMessage

    state = {"messages": [AIMessage(content="only-ai")]}
    assert last_message_text(state, human_only=True) == ""


def test_render_jinja_basic() -> None:
    assert render_jinja("Hello {{ name }}", {"name": "World"}) == "Hello World"


def test_render_jinja_undefined_raises() -> None:
    # StrictUndefined is not enabled, but attribute access on undefined raises.
    with pytest.raises(UndefinedError):
        render_jinja("{{ missing.attr }}", {})


def test_render_jinja_sandbox_blocks_unsafe_access() -> None:
    # The sandbox forbids traversing into internals like __mro__ (SPEC §10.5).
    with pytest.raises(SecurityError):
        render_jinja("{{ obj.__class__.__mro__ }}", {"obj": object()})


def test_eval_predicate_true_and_false() -> None:
    assert eval_predicate("count > 3", {"count": 5}) is True
    assert eval_predicate("count > 3", {"count": 1}) is False


def test_eval_predicate_undefined_to_none() -> None:
    # missing variable resolves to None → comparison falsey, no raise
    assert eval_predicate("missing", {}) is False


def test_render_prompt_substitutes_str() -> None:
    assert render_prompt("Hi {name}", {"name": "Ada"}) == "Hi Ada"


def test_render_prompt_missing_var_becomes_empty() -> None:
    assert render_prompt("A{gap}B", {}) == "AB"
    assert render_prompt("A{gap}B", {"gap": None}) == "AB"


def test_render_prompt_message_value() -> None:
    out = render_prompt("Said: {msg}", {"msg": Message(role="user", content="yo")})
    assert out == "Said: yo"


def test_render_prompt_json_serializes_dict() -> None:
    out = render_prompt("data={payload}", {"payload": {"a": 1}})
    assert out == 'data={"a": 1}'


def test_render_prompt_default_str_serializes_object() -> None:
    class Weird:
        def __repr__(self) -> str:
            return "WEIRD"

    # json.dumps with default=str stringifies unknown values → quoted string
    out = render_prompt("x={val}", {"val": Weird()})
    assert out == 'x="WEIRD"'


def test_render_prompt_typeerror_falls_back_to_str() -> None:
    # A tuple dict key is not JSON-serializable even with default=str (keys are
    # not passed through default) → json.dumps raises TypeError → str() fallback.
    value = {(1, 2): "x"}
    out = render_prompt("x={val}", {"val": value})
    assert out == f"x={value!s}"


def test_render_prompt_double_brace_escaped_to_single() -> None:
    # {{literal}} is escaped away from substitution and collapses to single braces
    assert render_prompt("{{keep}} {name}", {"name": "N"}) == "{keep} N"


def test_render_prompt_ignores_non_identifier_braces() -> None:
    # leading digit is not a valid placeholder name → left untouched
    assert render_prompt("{1bad}", {"1bad": "x"}) == "{1bad}"
