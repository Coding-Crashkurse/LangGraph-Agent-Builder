"""Canonical serialization: deterministic order, layout never semantic."""

from __future__ import annotations

import yaml

from langgraph_agent_builder.serialization import (
    canonical_definition_dict,
    dump_definition_yaml,
)
from tests.conftest import definition


def test_nodes_and_edges_sorted() -> None:
    shuffled = definition()
    shuffled["nodes"].reverse()
    shuffled["edges"].reverse()
    canonical = canonical_definition_dict(shuffled)
    assert [n["id"] for n in canonical["nodes"]] == ["call_1", "end_1", "start_1"]
    assert canonical["edges"][0]["from"] == "call_1.text"


def test_moving_a_node_only_changes_layout() -> None:
    """CLAUDE.md invariant 6: canvas moves never change semantic content."""
    before = definition()
    after = definition()
    after["layout"] = {"nodes": {"start_1": {"x": 999, "y": 999}}}
    a, b = canonical_definition_dict(before), canonical_definition_dict(after)
    a.pop("layout")
    b.pop("layout")
    assert a == b


def test_unparseable_draft_still_canonicalizes_deterministically() -> None:
    draft = definition()
    draft["nodes"][1]["config"] = {}  # llm_call not parseable
    draft["nodes"].reverse()
    once = dump_definition_yaml(draft)
    twice = dump_definition_yaml(yaml.safe_load(once))
    assert once == twice
    assert [n["id"] for n in yaml.safe_load(once)["nodes"]] == ["call_1", "end_1", "start_1"]


def test_yaml_dump_key_order_follows_schema() -> None:
    text = dump_definition_yaml(definition())
    top_keys = [
        line.split(":")[0] for line in text.splitlines() if line and line[0] not in (" ", "-")
    ]
    assert top_keys == [
        "schema_version",
        "name",
        "display_name",
        "description",
        "tags",
        "expose",
        "nodes",
        "edges",
        "layout",
    ]
