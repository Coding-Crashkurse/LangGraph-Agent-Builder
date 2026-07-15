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


def test_pinned_schema_matches_the_installed_agentplane_release() -> None:
    """The committed schema must equal the installed agentplane's exported schema.

    Validating examples (below) only catches drift on fields an example happens
    to exercise. This pins the whole contract: if a future ``agentplane-core``
    bump changes the schema, this fails until the pin and this file are
    refreshed together — the deliberate-upgrade gate (CLAUDE.md invariant 7),
    not a silent divergence.
    """
    from agentplane_core.schema_export import export_schema_json

    committed = SCHEMA_PATH.read_text(encoding="utf-8")
    assert committed == export_schema_json(), (
        "schemas/flow-definition.schema.json is out of sync with the installed "
        "agentplane-core. Refresh it alongside the version pin:\n"
        "  uv run python -m agentplane_core.schema_export > schemas/flow-definition.schema.json"
    )


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_exported_examples_validate_against_pinned_schema(
    path: Path, validator: Draft202012Validator
) -> None:
    exported = canonical_definition_dict(yaml.safe_load(path.read_text(encoding="utf-8")))
    errors = sorted(validator.iter_errors(exported), key=lambda e: list(e.absolute_path))
    assert not errors, "\n".join(
        f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors
    )
