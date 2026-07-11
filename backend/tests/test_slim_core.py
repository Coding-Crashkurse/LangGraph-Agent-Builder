"""Core architecture guardrails (SPEC §1.5 slim core, §4.8 no-eval, §15.6).

These tests defend two differentiator walls that are easy to erode silently:

1. **Slim core** — `import langgraph_agent_builder` must not pull a vendor SDK into ``sys.modules``.
   Providers/backends are optional extras, lazily imported *inside methods*
   (SPEC §2.3/§8b.2). A regression that module-loads e.g. ``qdrant-client`` at
   import time would break the "one slim package" promise without any other test
   noticing. The import-linter contract in ``pyproject.toml`` is the static
   guard; this is the runtime backstop, measured in a *fresh* interpreter.
2. **No eval, ever** — FlowSpec never carries executable code and the compiler
   never ``eval``/``exec``s user input (SPEC §4.8/§10.5/§18.3). This is the
   safety inversion of Langflow's ``code``-string ``compile``+``exec`` substrate
   (root of GHSA-2wcq-pvw2-xh7v / GHSA-mfp9-86w4-493f).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import langgraph_agent_builder
from langgraph_agent_builder.schema.flowspec import FlowSpec, NodeSpec

_LAB_ROOT = Path(langgraph_agent_builder.__file__).resolve().parent

# Vendor SDKs that must stay out of the base install's import graph. Vector
# clients are also pinned by the import-linter "core stays vector-vendor-free"
# contract; the LLM providers and heavy ML libs are covered here at runtime.
_FORBIDDEN_AT_IMPORT = (
    "qdrant_client",
    "weaviate",
    "chromadb",
    "pgvector",
    "langchain_openai",
    "langchain_anthropic",
    "langchain_ollama",
    "torch",
    "transformers",
)


def _iter_source_files() -> list[Path]:
    return [p for p in _LAB_ROOT.rglob("*.py") if "_static" not in p.parts]


def test_import_lga_pulls_no_vendor_sdk() -> None:
    """`import langgraph_agent_builder` in a clean interpreter loads zero vendor SDKs (§1.5-5)."""
    script = (
        "import sys, importlib\n"
        "importlib.import_module('langgraph_agent_builder')\n"
        "import langgraph_agent_builder\n"
        "langgraph_agent_builder.create_app\n"  # touch the public embedding API too
        f"forbidden = {list(_FORBIDDEN_AT_IMPORT)!r}\n"
        "present = sorted(m for m in forbidden if m in sys.modules)\n"
        "print(','.join(present))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    leaked = [m for m in result.stdout.strip().split(",") if m]
    assert not leaked, (
        f"`import langgraph_agent_builder` leaked vendor SDK(s) into sys.modules: {leaked}. "
        "Vendor imports must stay lazy (inside methods) — see SPEC §2.3/§8b.2."
    )


def test_no_eval_or_exec_in_source() -> None:
    """No lab module calls the ``eval``/``exec`` builtins (§4.8/§10.5).

    Method calls like ``builder.compile()`` / ``re.compile()`` are ``ast.Attribute``
    and are intentionally not matched — only bare-name ``eval(...)``/``exec(...)``.
    """
    offenders: list[str] = []
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"eval", "exec"}
            ):
                rel = path.relative_to(_LAB_ROOT.parent)
                offenders.append(f"{rel}:{node.lineno} calls {node.func.id}()")
    assert not offenders, (
        "lab must never eval/exec user input (SPEC §4.8/§18.3). Found:\n  " + "\n  ".join(offenders)
    )


def test_flowspec_carries_no_executable_code() -> None:
    """FlowSpec/NodeSpec have no field that could carry executable code (§4.8)."""
    node_fields = set(NodeSpec.model_fields)
    banned = {"code", "source", "script", "func", "callable"}
    leaked = node_fields & banned
    assert not leaked, f"NodeSpec exposes code-carrying field(s): {leaked}"

    schema_text = str(FlowSpec.model_json_schema())
    for bad in ('"code"', "'code'"):
        assert bad not in schema_text, (
            "FlowSpec JSON schema exposes a 'code' property — components are "
            "installed classes referenced by component_id, never inline code."
        )
