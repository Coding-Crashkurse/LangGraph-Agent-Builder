"""Normative interrupt payloads (SPEC §5.5).

Single source of truth for Playground modals AND A2A input-required messages —
do not fork the shape.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ApprovalRequest(BaseModel):
    kind: Literal["approval"] = "approval"
    prompt: str
    context: dict[str, Any] = Field(default_factory=dict)
    options: list[str] = Field(default_factory=lambda: ["approve", "reject"])


class InputRequest(BaseModel):
    kind: Literal["free_text"] = "free_text"
    prompt: str
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")

    model_config = {"populate_by_name": True}


def parse_approval_resume(payload: Any, options: list[str]) -> dict[str, Any] | None:
    """Normalize a resume payload for kind=approval (SPEC §7.7-4).

    Accepts {"decision": ..., "comment": ...} dicts or plain text parsed
    case-insensitively against options. Returns None when unparseable
    (caller stays input-required and re-prompts).
    """
    if isinstance(payload, dict) and "decision" in payload:
        decision = str(payload["decision"]).strip().lower()
        if decision in [o.lower() for o in options]:
            return {"decision": decision, "comment": payload.get("comment")}
        return None
    if isinstance(payload, str):
        text = payload.strip().lower()
        for option in options:
            if text == option.lower():
                return {"decision": option.lower(), "comment": None}
        return None
    return None


def parse_input_resume(payload: Any, schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize a resume payload for kind=free_text (SPEC §7.7-4)."""
    if isinstance(payload, dict):
        if schema is not None:
            import jsonschema  # type: ignore[import-untyped]  # jsonschema ships no stubs

            try:
                jsonschema.validate(payload, schema)
            except jsonschema.ValidationError:
                return None
            return payload
        if "text" in payload:
            return {"text": str(payload["text"])}
        return payload
    if isinstance(payload, str):
        if schema is not None:
            return None
        return {"text": payload}
    return None
