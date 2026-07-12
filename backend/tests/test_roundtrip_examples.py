"""Round-trip: ``parse(serialize(flow)) == flow`` over examples/ (CLAUDE.md)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from agentplane_core import FlowDefinition, validate_structure

from langgraph_agent_builder.serialization import dump_definition_yaml
from tests.conftest import EXAMPLES_DIR

EXAMPLES = sorted(EXAMPLES_DIR.glob("*.flow.yaml"))


def _load(path: Path) -> FlowDefinition:
    return FlowDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_parse_serialize_roundtrip(path: Path) -> None:
    flow = _load(path)
    text = dump_definition_yaml(flow.canonical_dict())
    reparsed = FlowDefinition.model_validate(yaml.safe_load(text))
    assert reparsed == flow


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_serialization_is_stable(path: Path) -> None:
    flow = _load(path)
    once = dump_definition_yaml(flow.canonical_dict())
    twice = dump_definition_yaml(
        FlowDefinition.model_validate(yaml.safe_load(once)).canonical_dict()
    )
    assert once == twice


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_examples_are_error_free(path: Path) -> None:
    issues = validate_structure(_load(path))
    errors = [i for i in issues if i.severity == "error"]
    assert not errors, [f"{i.code}@{i.path}: {i.message}" for i in errors]


def test_examples_exist() -> None:
    assert EXAMPLES, "examples/ must ship canonical FlowDefinition YAML files"
