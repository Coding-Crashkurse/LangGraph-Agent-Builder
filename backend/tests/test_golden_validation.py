"""Golden validation tests: known-bad flows → expected E0xx codes.

Codes must match the platform error registry exactly (CLAUDE.md); these pin
the contract the frontend relies on for issue rendering and node focus.
"""

from __future__ import annotations

from typing import Any

import pytest
from agentplane_core import validate_structure

from tests.conftest import definition


def _codes(defn: dict[str, Any]) -> set[str]:
    return {i.code for i in validate_structure(defn)}


def test_valid_definition_is_clean() -> None:
    assert _codes(definition()) == set()


def test_e001_unsupported_schema_version() -> None:
    assert "E001" in _codes(definition(schema_version=2))


def test_e002_unknown_node_type() -> None:
    bad = definition()
    # subflow is reserved in the platform spec but not implemented (E002)
    bad["nodes"].append({"id": "x_1", "type": "subflow", "version": 1, "config": {}})
    assert "E002" in _codes(bad)


def test_e002_unknown_node_version() -> None:
    bad = definition()
    bad["nodes"][1]["version"] = 99
    assert "E002" in _codes(bad)


def test_e010_missing_required_config() -> None:
    bad = definition()
    bad["nodes"][1]["config"] = {"resource": "default-llm"}  # llm_call without prompt
    assert "E010" in _codes(bad)


def test_e011_invalid_field_format() -> None:
    bad = definition()
    bad["nodes"][1]["config"]["stream"] = "yes-please"
    assert "E011" in _codes(bad)


def test_e023_credential_like_literal() -> None:
    bad = definition()
    bad["nodes"][1]["config"]["prompt"] = "use key sk-abcdefghijklmnop1234 for calls"
    assert "E023" in _codes(bad)


def test_e030_end_unreachable() -> None:
    assert "E030" in _codes(definition(edges=[]))


def test_e031_cycle_detected() -> None:
    bad = definition()
    bad["nodes"].insert(
        2,
        {
            "id": "loopy_1",
            "type": "llm_call",
            "version": 1,
            "config": {"resource": "default-llm", "prompt": "{message} {echo}"},
        },
    )
    bad["edges"] = [
        {"from": "start_1.message", "to": "call_1.message"},
        {"from": "call_1.text", "to": "loopy_1.message"},
        {"from": "loopy_1.text", "to": "call_1.message"},
        {"from": "call_1.text", "to": "end_1.input"},
    ]
    assert "E031" in _codes(bad)


def test_e032_dangling_edge() -> None:
    bad = definition()
    bad["edges"].append({"from": "ghost_1.out", "to": "call_1.message"})
    assert "E032" in _codes(bad)


def test_e032_incompatible_port_types() -> None:
    bad = definition()
    bad["nodes"].append(
        {
            "id": "kb_1",
            "type": "retrieval",
            "version": 1,
            "config": {"resource": "kb", "collection": "docs"},
        }
    )
    # documents -> json arg port is not connectable (only documents -> text is)
    bad["nodes"].append(
        {
            "id": "tool_1",
            "type": "mcp_tool",
            "version": 1,
            "config": {"resource": "tools", "tool": "t", "args": {"data": "data"}},
        }
    )
    bad["edges"].append({"from": "start_1.message", "to": "kb_1.query"})
    bad["edges"].append({"from": "kb_1.documents", "to": "tool_1.data"})
    codes = _codes(bad)
    assert "E032" in codes


def test_e040_duplicate_node_id() -> None:
    bad = definition()
    bad["nodes"].append(dict(bad["nodes"][1]))
    assert "E040" in _codes(bad)


def test_e040_duplicate_edge() -> None:
    bad = definition()
    bad["edges"].append(dict(bad["edges"][0]))
    assert "E040" in _codes(bad)


def test_e050_mcp_without_tool_name() -> None:
    bad = definition(expose={"kind": "mcp"})
    assert "E050" in _codes(bad)


@pytest.mark.parametrize(
    "issue_code",
    ["W003"],
)
def test_w003_stream_ignored_for_mcp(issue_code: str) -> None:
    flow = definition(expose={"kind": "mcp", "tool_name": "do_things", "tool_description": "d"})
    flow["nodes"][1]["config"]["stream"] = True
    issues = validate_structure(flow)
    assert issue_code in {i.code for i in issues}
    assert all(i.severity == "warning" for i in issues if i.code == issue_code)


def test_paths_point_at_nodes_and_fields() -> None:
    """`ValidationIssue.path` drives node/field focus in the frontend."""
    bad = definition()
    bad["nodes"][1]["config"] = {"resource": "default-llm"}
    issues = validate_structure(bad)
    paths = {i.path for i in issues if i.code == "E010"}
    assert any(p.startswith("nodes/call_1/config") for p in paths)
