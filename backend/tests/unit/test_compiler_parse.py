"""Unit tests for lga.compiler.parse (P1: FlowSpec JSON → IR skeleton, E00x)."""

from __future__ import annotations

import copy
from typing import Any

from lga.compiler import parse as parse_pass
from lga.schema.diagnostics import DiagnosticCode
from tests.conftest import hello_spec


def _codes(diagnostics: list[Any]) -> list[DiagnosticCode]:
    return [d.code for d in diagnostics]


def test_valid_spec_parses_clean() -> None:
    spec, diagnostics = parse_pass.parse(hello_spec())
    assert spec is not None
    assert diagnostics == []
    assert spec.flow.slug == "hello"


def test_schema_invalid_returns_e001_and_no_spec() -> None:
    spec, diagnostics = parse_pass.parse({"schema_version": "99", "flow": {}})
    assert spec is None
    assert DiagnosticCode.E001 in _codes(diagnostics)


def test_duplicate_node_id_is_e003() -> None:
    raw = hello_spec()
    dup = copy.deepcopy(raw["nodes"][1])  # another node also with id "fake"
    raw["nodes"].append(dup)
    _, diagnostics = parse_pass.parse(raw)
    dup_diags = [d for d in diagnostics if d.code == DiagnosticCode.E003]
    assert dup_diags
    assert any("duplicate node id" in d.message for d in dup_diags)
    assert dup_diags[0].node_id == "fake"


def test_reserved_node_id_wrong_component_is_e003() -> None:
    raw = hello_spec()
    raw["nodes"][0]["component_id"] = "lga.testing.fake_llm"  # "start" must be lga.io.start
    _, diagnostics = parse_pass.parse(raw)
    diag = next(d for d in diagnostics if d.code == DiagnosticCode.E003)
    assert diag.node_id == "start"
    assert "lga.io.start" in diag.message


def test_duplicate_edge_id_is_e001() -> None:
    raw = hello_spec()
    clone = copy.deepcopy(raw["edges"][0])  # reuse id "e1" on a valid endpoint pair
    clone["target"] = {"node": "end", "input": "message"}
    raw["edges"].append(clone)
    _, diagnostics = parse_pass.parse(raw)
    assert any(
        d.code == DiagnosticCode.E001 and "duplicate edge id" in d.message for d in diagnostics
    )


def test_edge_referencing_unknown_node_is_e001() -> None:
    raw = hello_spec()
    raw["edges"].append(
        {
            "id": "ghost",
            "kind": "data",
            "source": {"node": "does_not_exist", "output": "message"},
            "target": {"node": "end", "input": "message"},
        }
    )
    _, diagnostics = parse_pass.parse(raw)
    unknown = [
        d for d in diagnostics if d.code == DiagnosticCode.E001 and "unknown node" in d.message
    ]
    assert unknown
    assert unknown[0].edge_id == "ghost"
    assert "does_not_exist" in unknown[0].message
