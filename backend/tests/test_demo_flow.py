"""The seeded demo flow must always validate (CLAUDE.md §16)."""

import json
from pathlib import Path

from graphforge.compiler.build import validate
from graphforge.compiler.spec import FlowSpec
from graphforge.components.registry import registry

DEMO = Path(__file__).resolve().parents[2] / "examples" / "flows" / "library_rag.json"


def test_library_rag_demo_flow_validates():
    registry.load(include_testing=False)
    try:
        spec = FlowSpec.model_validate(json.loads(DEMO.read_text(encoding="utf-8")))
        issues = validate(spec, registry)
        errors = [i for i in issues if i.severity == "error"]
        assert errors == [], [i.message for i in errors]
        assert spec.publish.a2a and spec.publish.mcp
        assert spec.publish.mcp_tool.name == "ask_library"
    finally:
        registry.load(include_testing=True)
