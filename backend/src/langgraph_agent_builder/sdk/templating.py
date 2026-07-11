"""Sandboxed jinja2 templating + message helpers (SPEC §10.5: no attribute traversal)."""

from __future__ import annotations

import json
import re
from typing import Any

from jinja2.sandbox import SandboxedEnvironment

from langgraph_agent_builder.sdk.ports import Message

_env = SandboxedEnvironment(autoescape=False)
_env.globals.clear()  # no range/dict/etc — data-only templates

PROMPT_VAR_RE = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")


def message_text(message: Any) -> str:
    """Plain text of a Message / LangChain BaseMessage / str."""
    if message is None:
        return ""
    if isinstance(message, str):
        return message
    if isinstance(message, Message):
        return message.content
    content = getattr(message, "content", None)
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
    return str(message)


def last_message_text(state: dict[str, Any], *, human_only: bool = False) -> str:
    messages = list(state.get("messages") or [])
    if human_only:
        messages = [m for m in messages if getattr(m, "type", "") == "human"]
    return message_text(messages[-1]) if messages else ""


def render_jinja(template: str, variables: dict[str, Any]) -> str:
    """Sandboxed jinja render; template errors raise (fail loudly)."""
    return _env.from_string(template).render(**variables)


def eval_predicate(expression: str, variables: dict[str, Any]) -> bool:
    """Sandboxed jinja expression → truthiness (Rule Router predicates)."""
    return bool(_env.compile_expression(expression, undefined_to_none=True)(**variables))


def render_prompt(template: str, values: dict[str, Any]) -> str:
    """Langflow-style single-brace prompt: `{var}` placeholders (SPEC §4.2 PromptInput)."""

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        value = values.get(name)
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, Message) or hasattr(value, "content"):
            return message_text(value)
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            return str(value)

    return PROMPT_VAR_RE.sub(_sub, template).replace("{{", "{").replace("}}", "}")
