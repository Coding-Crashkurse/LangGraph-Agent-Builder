"""Canonical FlowDefinition (de)serialization for the builder.

The backend is the single serializer/deserializer of the definition format:
the frontend never persists its own graph format. Drafts are stored as
FlowDefinition JSON objects — possibly *incomplete* (a half-configured canvas
must always be saveable), therefore raw storage accepts any mapping in the
FlowDefinition shape and validation stays advisory.

Canonical ordering (nodes by id, edges by (from, to), keys in schema order)
comes from ``agentplane_core.FlowDefinition`` whenever the draft parses; for
not-yet-valid drafts a best-effort raw canonicalization keeps exports and
diffs deterministic without silently changing any semantic content.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import yaml
from agentplane_core import FlowDefinition, ValidationIssue, validate_structure
from pydantic import ValidationError

from langgraph_agent_builder.errors import InvalidDefinitionError

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")

# Top-level / node key order of the FlowDefinition schema (SPEC §3.1).
_TOP_KEY_ORDER = (
    "schema_version",
    "name",
    "display_name",
    "description",
    "tags",
    "expose",
    "nodes",
    "edges",
    "layout",
)
_NODE_KEY_ORDER = ("id", "type", "version", "config")
_EDGE_KEY_ORDER = ("from", "to")


def parse_definition(data: Mapping[str, Any]) -> FlowDefinition:
    """Parse a mapping into a FlowDefinition; structured issues on failure."""
    try:
        return FlowDefinition.model_validate(dict(data))
    except ValidationError as exc:
        issues = [i for i in validate_structure(dict(data)) if i.severity == "error"]
        raise InvalidDefinitionError(
            f"definition does not parse: {exc.error_count()} error(s)", issues
        ) from exc


def loads_definition_data(text: str) -> dict[str, Any]:
    """Parse YAML/JSON text into a raw definition mapping (no validation)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InvalidDefinitionError(f"not valid YAML/JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidDefinitionError("definition must be a YAML/JSON object")
    return data


def require_name(raw: Mapping[str, Any]) -> str:
    """The definition's ``name`` — required and slug-shaped even for drafts."""
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise InvalidDefinitionError(
            "definition needs a name",
            [
                ValidationIssue(
                    code="E010", severity="error", path="name", message="name is required"
                )
            ],
        )
    if not _NAME_RE.match(name):
        raise InvalidDefinitionError(
            f"invalid flow name {name!r}",
            [
                ValidationIssue(
                    code="E011",
                    severity="error",
                    path="name",
                    message="name must match ^[a-z0-9][a-z0-9-]{1,62}$",
                )
            ],
        )
    return name


def _ordered(mapping: Mapping[str, Any], key_order: tuple[str, ...]) -> dict[str, Any]:
    known = {k: mapping[k] for k in key_order if k in mapping}
    rest = {k: v for k, v in mapping.items() if k not in known}
    return {**known, **rest}


def _raw_canonical(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Best-effort canonical ordering for drafts that do not parse yet."""
    data = _ordered(raw, _TOP_KEY_ORDER)
    nodes = data.get("nodes")
    if isinstance(nodes, list):
        data["nodes"] = sorted(
            (_ordered(n, _NODE_KEY_ORDER) if isinstance(n, Mapping) else n for n in nodes),
            key=lambda n: str(n.get("id", "")) if isinstance(n, Mapping) else "",
        )
    edges = data.get("edges")
    if isinstance(edges, list):
        data["edges"] = sorted(
            (_ordered(e, _EDGE_KEY_ORDER) if isinstance(e, Mapping) else e for e in edges),
            key=lambda e: (
                (str(e.get("from", "")), str(e.get("to", "")))
                if isinstance(e, Mapping)
                else ("", "")
            ),
        )
    return data


def canonical_definition_dict(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical JSON-mode dict: authoritative via core when the draft parses."""
    try:
        return FlowDefinition.model_validate(dict(raw)).canonical_dict()
    except ValidationError:
        return _raw_canonical(raw)


def dump_definition_yaml(raw: Mapping[str, Any]) -> str:
    """Deterministic canonical YAML (git-safe, diff-stable)."""
    text: str = yaml.safe_dump(
        canonical_definition_dict(raw),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )
    return text
