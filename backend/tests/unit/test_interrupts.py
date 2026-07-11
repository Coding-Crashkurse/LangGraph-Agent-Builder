"""Unit tests for sdk.interrupts (normative resume-payload parsing, SPEC §5.5/§7.7)."""

from __future__ import annotations

from langgraph_agent_builder.sdk.interrupts import (
    ApprovalRequest,
    InputRequest,
    parse_approval_resume,
    parse_input_resume,
)

OPTIONS = ["approve", "reject"]


def test_approval_request_defaults() -> None:
    req = ApprovalRequest(prompt="ok?")
    assert req.kind == "approval"
    assert req.options == ["approve", "reject"]
    assert req.context == {}


def test_input_request_schema_alias() -> None:
    # populate_by_name + alias="schema": both spellings accepted, dumps under alias
    req = InputRequest(prompt="name?", schema={"type": "object"})  # type: ignore[call-arg]
    assert req.schema_ == {"type": "object"}
    assert req.model_dump(by_alias=True)["schema"] == {"type": "object"}


def test_approval_resume_dict_decision_valid() -> None:
    out = parse_approval_resume({"decision": "Approve", "comment": "lgtm"}, OPTIONS)
    assert out == {"decision": "approve", "comment": "lgtm"}


def test_approval_resume_dict_decision_no_comment() -> None:
    out = parse_approval_resume({"decision": "reject"}, OPTIONS)
    assert out == {"decision": "reject", "comment": None}


def test_approval_resume_dict_decision_invalid() -> None:
    assert parse_approval_resume({"decision": "maybe"}, OPTIONS) is None


def test_approval_resume_plain_text_match_case_insensitive() -> None:
    assert parse_approval_resume("APPROVE", OPTIONS) == {"decision": "approve", "comment": None}


def test_approval_resume_plain_text_no_match() -> None:
    assert parse_approval_resume("perhaps", OPTIONS) is None


def test_approval_resume_unparseable_type() -> None:
    assert parse_approval_resume(42, OPTIONS) is None
    assert parse_approval_resume(None, OPTIONS) is None


def test_input_resume_dict_no_schema_with_text() -> None:
    assert parse_input_resume({"text": 99}, None) == {"text": "99"}


def test_input_resume_dict_no_schema_no_text_passthrough() -> None:
    payload = {"foo": "bar"}
    assert parse_input_resume(payload, None) == payload


def test_input_resume_plain_str_no_schema() -> None:
    assert parse_input_resume("hello", None) == {"text": "hello"}


def test_input_resume_str_rejected_when_schema_present() -> None:
    assert parse_input_resume("hello", {"type": "object"}) is None


def test_input_resume_dict_valid_against_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
    }
    payload = {"n": 5}
    assert parse_input_resume(payload, schema) == payload


def test_input_resume_dict_invalid_against_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
    }
    # missing required "n" → validation fails → None
    assert parse_input_resume({"other": 1}, schema) is None


def test_input_resume_unparseable_type() -> None:
    assert parse_input_resume(123, None) is None
    assert parse_input_resume(None, None) is None
