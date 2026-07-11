"""Bundled starter templates (SPEC §9.9) — read-only FlowSpecs for the gallery."""

from __future__ import annotations

import copy
from typing import Any

from langgraph_agent_builder.services.bootstrap import STARTER_FLOWS


def _template_id(spec: dict[str, Any]) -> str:
    return str(spec["flow"]["slug"])


def list_templates() -> list[dict[str, Any]]:
    """Gallery metadata (id, name, description, preview) — never the raw spec."""
    out: list[dict[str, Any]] = []
    for spec in STARTER_FLOWS:
        flow = spec["flow"]
        out.append(
            {
                "id": _template_id(spec),
                "name": flow["name"],
                "description": flow.get("description", ""),
                "icon": flow.get("icon", "bot"),
                "node_count": len(spec.get("nodes", [])),
            }
        )
    return out


def get_template(template_id: str) -> dict[str, Any] | None:
    for spec in STARTER_FLOWS:
        if _template_id(spec) == template_id:
            return copy.deepcopy(spec)
    return None


def instantiate(template_id: str, existing_slugs: set[str]) -> dict[str, Any] | None:
    """Materialize a template into a fresh, unique-slug draft FlowSpec."""
    spec = get_template(template_id)
    if spec is None:
        return None
    base = spec["flow"]["slug"].removeprefix("starter-")
    slug = base
    i = 2
    while slug in existing_slugs:
        slug = f"{base}-{i}"
        i += 1
    spec["flow"]["slug"] = slug
    spec["flow"]["name"] = spec["flow"]["name"].replace("Starter: ", "")
    return spec
