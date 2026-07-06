"""Export-to-Python golden (SPEC §5.7): exported file ⇒ identical topology."""

from __future__ import annotations

import importlib.util
import sys

from lga.compiler import compile_flow
from lga.compiler.export_python import export_python
from lga.schema.flowspec import parse_flowspec
from lga.sdk.registry import get_registry
from tests.conftest import approval_spec, hello_spec


def _load_module(source: str, tmp_path, name: str):
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _topology(graph):
    drawn = graph.get_graph()
    return (
        sorted(drawn.nodes),
        sorted((e.source, e.target) for e in drawn.edges),
    )


def test_exported_hello_matches_compiler_topology(tmp_path):
    spec = parse_flowspec(hello_spec("export-hello"))
    module = _load_module(export_python(spec, get_registry()), tmp_path, "exported_hello")
    compiled = compile_flow(spec, use_cache=False)
    assert _topology(module.graph) == _topology(compiled.graph)


def test_exported_router_flow_matches(tmp_path):
    spec = parse_flowspec(approval_spec("export-hitl"))
    module = _load_module(export_python(spec, get_registry()), tmp_path, "exported_hitl")
    compiled = compile_flow(spec, use_cache=False)
    assert _topology(module.graph) == _topology(compiled.graph)


async def test_exported_graph_runs_under_vanilla_langgraph(tmp_path):
    from langchain_core.messages import HumanMessage

    spec = parse_flowspec(hello_spec("export-run"))
    module = _load_module(export_python(spec, get_registry()), tmp_path, "exported_run")
    state = {
        "messages": [HumanMessage("hello")],
        "ports": {},
        "route": {},
        "run_meta": {"input_text": "hello", "run_id": "x", "thread_id": "y"},
    }
    result = await module.graph.ainvoke(state)
    assert any("Hello from LGA!" in str(v) for v in result.get("ports", {}).values())


def test_secret_refs_become_environ(tmp_path):
    spec_dict = hello_spec("export-secret")
    spec_dict["nodes"].append(
        {
            "id": "t",
            "component_id": "lga.io.text_input",
            "component_version": "1.0.0",
            "config": {"value": {"$secret": "my_api_key"}},
            "position": {"x": 0, "y": 0},
        }
    )
    spec_dict["edges"].append(
        {
            "id": "et",
            "kind": "data",
            "source": {"node": "t", "output": "text"},
            "target": {"node": "end", "input": "text"},
        }
    )
    import os

    os.environ["LGA_CRED_MY_API_KEY"] = "sk-test"
    try:
        source = export_python(parse_flowspec(spec_dict), get_registry())
    finally:
        del os.environ["LGA_CRED_MY_API_KEY"]
    assert 'os.environ["MY_API_KEY"]' in source
