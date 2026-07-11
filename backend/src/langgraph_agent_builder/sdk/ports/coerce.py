"""Registered coercions — pure functions auto-inserted on edges (SPEC §4.3).

Everything not listed here requires the explicit `Type Convert` component.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langgraph_agent_builder.sdk.ports import Document, Message, PortSpec

DEFAULT_DOCUMENTS_TEMPLATE = "{page_content}"


def message_to_text(value: Any) -> str:
    if isinstance(value, Message):
        return value.content
    if isinstance(value, dict):
        return str(value.get("content", ""))
    return str(value)


def text_to_message(value: Any) -> Message:
    return Message(role="user", content=str(value))


def documents_to_text(value: Any) -> str:
    parts: list[str] = []
    for doc in value or []:
        if isinstance(doc, Document):
            parts.append(doc.page_content)
        elif isinstance(doc, dict):
            parts.append(str(doc.get("page_content", "")))
        else:
            parts.append(str(doc))
    return "\n\n".join(parts)


def json_to_text(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def table_to_json(value: Any) -> dict[str, Any]:
    return {"rows": list(value or [])}


def table_to_text(value: Any) -> str:
    """Render a list-of-dict Table as a GitHub-flavoured markdown table."""
    rows = list(value or [])
    if not rows:
        return ""
    columns: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            for key in row:
                if key not in columns:
                    columns.append(str(key))
    if not columns:
        return "\n".join(str(r) for r in rows)
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| "
        + " | ".join(str(row.get(c, "") if isinstance(row, dict) else "") for c in columns)
        + " |"
        for row in rows
    ]
    return "\n".join([header, sep, *body])


def wrap_list(value: Any) -> list[Any]:
    return [value]


# (source schema_ref, target schema_ref) → coercion name
_EDGE_COERCIONS: dict[tuple[str, str], str] = {
    ("lab:Message", "lab:Text"): "message_to_text",
    ("lab:Text", "lab:Message"): "text_to_message",
    ("lab:Documents", "lab:Text"): "documents_to_text",
    ("lab:Json", "lab:Text"): "json_to_text",
    ("lab:Table", "lab:Json"): "table_to_json",
    ("lab:Table", "lab:Text"): "table_to_text",
}

FUNCTIONS: dict[str, Callable[[Any], Any]] = {
    "message_to_text": message_to_text,
    "text_to_message": text_to_message,
    "documents_to_text": documents_to_text,
    "json_to_text": json_to_text,
    "table_to_json": table_to_json,
    "table_to_text": table_to_text,
    "wrap_list": wrap_list,
}


def find(source: PortSpec, target: PortSpec) -> str | None:
    return _EDGE_COERCIONS.get((source.schema_ref, target.schema_ref))


def apply(name: str, value: Any) -> Any:
    for step in name.split("+"):
        value = FUNCTIONS[step](value)
    return value
