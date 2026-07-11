"""Bounded ``{{ expr }}`` expression language for opt-in config fields (SPEC §10.5).

A deliberately *non*-Turing-complete templating layer over the sandboxed jinja
environment: path access, a fixed pipe/function whitelist, no attribute
traversal beyond data, no ``eval``/``exec``. This is the capability the four
legacy compensation nodes (``current_date`` / ``json_extract`` / ``parser`` /
``type_convert``) were faking — enabling it on a string field lets an author
write e.g. ``{{ input.title | upper }}`` or ``{{ state.data.count | round }}``
inline (n8n's full-JS is the anti-pattern; Dify's bounded approach ages better).

Two evaluation modes (:func:`render_expression`):

* the value is *exactly* one ``{{ … }}`` (whitespace aside) → the expression is
  compiled and its **typed** Python result returned (list / number / datetime…);
* otherwise the value is rendered as a mixed **string** template.

Only three scope roots are ever exposed — ``input`` (the node's bound
input-port values), ``state`` (a safe excerpt: ``messages`` / ``data`` /
``vars``) and ``vars`` (the ``$var`` globals). Secrets are never in scope.

The environment is a dedicated ``SandboxedEnvironment`` (not the shared
``templating._env``) so its filter/global namespace can be locked to exactly the
whitelist without disturbing the predicate/``render_jinja`` surfaces.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from collections.abc import Mapping
from typing import Any

from jinja2 import ChainableUndefined, TemplateSyntaxError
from jinja2 import meta as _meta
from jinja2.filters import FILTERS as _JINJA_FILTERS
from jinja2.sandbox import SandboxedEnvironment

from langgraph_agent_builder.sdk.templating import message_text

# Scope roots + the two global callables. Anything else a template references
# that is not a filter is an "unknown path" (W205 at compile time).
ALLOWED_ROOTS: frozenset[str] = frozenset({"input", "state", "vars", "now", "today"})

# A ``{{ … }}`` block (non-greedy, dot matches newlines).
_EXPR_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)


# --------------------------------------------------------------------- globals
def now() -> _dt.datetime:
    """Current UTC timestamp (typed ``datetime``)."""
    return _dt.datetime.now(tz=_dt.UTC)


def today() -> _dt.date:
    """Current UTC date (typed ``date``)."""
    return _dt.datetime.now(tz=_dt.UTC).date()


# ------------------------------------------------------------------ custom filters
def _json_parse(value: Any) -> Any:
    """Parse a JSON string; already-decoded values pass through, junk → None."""
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(str(value))
    except (ValueError, TypeError):
        return None


def _json_dump(value: Any) -> str:
    """Serialize to a stable JSON string (sorted keys, non-ASCII preserved)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _split(value: Any, sep: str | None = None, maxsplit: int = -1) -> list[str]:
    """``str.split`` as a filter — default splits on runs of whitespace."""
    return str(value).split(sep, maxsplit)


def _regex_extract(value: Any, pattern: str, group: int = 0) -> str | None:
    """First regex match (or capture *group*); no match / bad pattern → None."""
    try:
        match = re.search(pattern, str(value))
    except re.error:
        return None
    if match is None:
        return None
    try:
        return match.group(group)
    except (IndexError, re.error):
        return None


_CUSTOM_FILTERS: dict[str, Any] = {
    "json_parse": _json_parse,
    "json_dump": _json_dump,
    "split": _split,
    "regex_extract": _regex_extract,
}

# jinja built-ins we re-expose verbatim (their decorators survive the copy).
_ALLOWED_BUILTIN_FILTERS: tuple[str, ...] = (
    "upper",
    "lower",
    "trim",
    "length",
    "default",
    "join",
    "replace",
    "round",
)


class _DataSandbox(SandboxedEnvironment):
    """Sandbox whose ``a.b`` prefers mapping **keys** over Python attributes.

    So ``input.items`` means the ``"items"`` key, never ``dict.items`` (and
    ``input.get`` / ``.keys`` / ``.pop`` can't reach dict internals). Aligns dot
    and subscript access and keeps traversal strictly over data (SPEC §10.5).
    """

    def getattr(self, obj: Any, attribute: str) -> Any:
        if isinstance(obj, Mapping):
            try:
                return obj[attribute]
            except (KeyError, TypeError):
                return self.undefined(obj=obj, name=attribute)
        return super().getattr(obj, attribute)


def _build_env() -> SandboxedEnvironment:
    env = _DataSandbox(autoescape=False, undefined=ChainableUndefined)
    # Lock the namespaces to exactly the whitelist (SPEC §10.5): only ``now`` /
    # ``today`` globals, only the 12 whitelisted filters, no ``is`` tests and no
    # ``range``/``dict``/… builtins.
    env.globals.clear()
    env.globals.update({"now": now, "today": today})
    env.filters.clear()
    env.filters.update({name: _JINJA_FILTERS[name] for name in _ALLOWED_BUILTIN_FILTERS})
    env.filters.update(_CUSTOM_FILTERS)
    env.tests.clear()
    return env


_EXPR_ENV = _build_env()

# The exact runtime whitelist (globals + filters) — 14 names, nothing else.
WHITELIST: frozenset[str] = frozenset({"now", "today", *_EXPR_ENV.filters})


# --------------------------------------------------------------------- public API
def has_expression(value: Any) -> bool:
    """True when *value* is a string carrying a ``{{`` expression delimiter.

    Fast-path guard: a value with no ``{{`` is returned unchanged. A lone/unclosed
    ``{{`` still counts as an expression so the compiler flags the typo (E018)
    instead of silently persisting a broken literal.
    """
    return isinstance(value, str) and "{{" in value


def render_expression(value: str, scope: Mapping[str, Any]) -> Any:
    """Evaluate ``{{ … }}`` in *value* against *scope* (``input`` / ``state`` / ``vars``).

    A whole-value single expression yields its **typed** Python result; mixed
    content renders to a **string**; a value with no ``{{ }}`` is returned as-is.
    Undefined paths resolve to ``None`` (``undefined_to_none`` / chainable
    undefined), so ``… | default(x)`` behaves as expected.
    """
    if not has_expression(value):
        return value
    variables = dict(scope)
    stripped = value.strip()
    if len(_EXPR_RE.findall(value)) == 1 and stripped.startswith("{{") and stripped.endswith("}}"):
        expr_src = stripped[2:-2].strip()
        if not expr_src:
            return ""
        return _EXPR_ENV.compile_expression(expr_src, undefined_to_none=True)(**variables)
    return _EXPR_ENV.from_string(value).render(**variables)


def state_excerpt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Safe, read-only ``FlowState`` view for expressions: ``messages`` / ``data`` / ``vars``.

    Messages are flattened to ``{role, content}`` dicts so path access works
    without exposing raw object attributes (SPEC §10.5 — no attribute traversal
    beyond data); ``ports`` / ``route`` / ``run_meta`` and any secrets are never
    included.
    """
    messages: list[dict[str, str]] = []
    for m in state.get("messages") or []:
        if isinstance(m, dict):
            messages.append({"role": str(m.get("role", "")), "content": str(m.get("content", ""))})
        else:
            messages.append({"role": str(getattr(m, "type", "")), "content": message_text(m)})
    return {
        "messages": messages,
        "data": dict(state.get("data") or {}),
        "vars": dict(state.get("vars") or {}),
    }


def analyze_expression(value: str) -> tuple[str | None, set[str]]:
    """Static analysis for the compiler (P3 validate).

    Returns ``(syntax_error, unknown_roots)``:

    * ``syntax_error`` — a jinja ``TemplateSyntaxError`` message (→ E018) or None;
    * ``unknown_roots`` — referenced root names outside :data:`ALLOWED_ROOTS`
      (→ W205, "references an unknown path").

    Only meaningful when :func:`has_expression` is True for *value*.
    """
    try:
        ast = _EXPR_ENV.parse(value)
    except TemplateSyntaxError as exc:
        return (exc.message or str(exc), set())
    unknown = set(_meta.find_undeclared_variables(ast)) - ALLOWED_ROOTS
    return (None, unknown)
