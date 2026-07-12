"""Contract test: exported examples validate against the PINNED platform schema.

A failing contract test means: upgrade the pin deliberately or fix the
mapping — never loosen the test (CLAUDE.md testing rules).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from langgraph_agent_builder.serialization import canonical_definition_dict
from tests.conftest import EXAMPLES_DIR, SCHEMA_PATH

EXAMPLES = sorted(EXAMPLES_DIR.glob("*.flow.yaml"))


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_schema_is_pinned() -> None:
    assert SCHEMA_PATH.exists(), "schemas/flow-definition.schema.json must be committed"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_exported_examples_validate_against_pinned_schema(
    path: Path, validator: Draft202012Validator
) -> None:
    exported = canonical_definition_dict(yaml.safe_load(path.read_text(encoding="utf-8")))
    errors = sorted(validator.iter_errors(exported), key=lambda e: list(e.absolute_path))
    assert not errors, "\n".join(
        f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors
    )
