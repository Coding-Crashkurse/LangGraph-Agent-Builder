"""Jinja-lite templating over FlowState: `{data.key}`, `{route}`, `{last_message}`.

Deliberately tiny — no logic, no filters. Unknown paths raise so template
mistakes fail loudly in the failed-task error instead of silently rendering."""

import json
import re
from typing import Any

from langchain_core.messages import BaseMessage

_PLACEHOLDER = re.compile(r"\{([a-zA-Z0-9_.]+)\}")


def message_text(message: BaseMessage | None) -> str:
    if message is None:
        return ""
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        chunks = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text", "")))
        return "".join(chunks)
    return str(content)


def last_message_text(state: dict[str, Any], *, human_only: bool = False) -> str:
    messages: list[BaseMessage] = list(state.get("messages") or [])
    if human_only:
        messages = [m for m in messages if getattr(m, "type", "") == "human"]
    return message_text(messages[-1]) if messages else ""


def resolve_path(state: dict[str, Any], path: str) -> Any:
    if path == "last_message":
        return last_message_text(state)
    if path == "last_human_message":
        return last_message_text(state, human_only=True)
    current: Any = state
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            raise ValueError(f"unknown state path '{path}' in template")
    return current


def render_template(template: str, state: dict[str, Any]) -> str:
    def _sub(match: re.Match[str]) -> str:
        value = resolve_path(state, match.group(1))
        if isinstance(value, str):
            return value
        if isinstance(value, BaseMessage):
            return message_text(value)
        try:
            return json.dumps(value, default=str, ensure_ascii=False)
        except TypeError:
            return str(value)

    return _PLACEHOLDER.sub(_sub, template)
