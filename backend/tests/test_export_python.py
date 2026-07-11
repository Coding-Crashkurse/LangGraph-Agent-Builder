"""Export-to-Python golden (SPEC §5.7): exported file ⇒ identical topology."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from langgraph.graph.state import CompiledStateGraph

from langgraph_agent_builder.compiler import compile_flow
from langgraph_agent_builder.compiler.export_python import export_python
from langgraph_agent_builder.schema.flowspec import parse_flowspec
from langgraph_agent_builder.schema.state import FlowState
from langgraph_agent_builder.sdk.registry import get_registry
from tests.conftest import approval_spec, hello_spec


def _load_module(source: str, tmp_path: Path, name: str) -> ModuleType:
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _topology(
    graph: CompiledStateGraph[FlowState],
) -> tuple[list[str], list[tuple[str, str]]]:
    drawn = graph.get_graph()
    return (
        sorted(drawn.nodes),
        sorted((e.source, e.target) for e in drawn.edges),
    )


def test_exported_hello_matches_compiler_topology(tmp_path: Path) -> None:
    spec = parse_flowspec(hello_spec("export-hello"))
    module = _load_module(export_python(spec, get_registry()), tmp_path, "exported_hello")
    compiled = compile_flow(spec, use_cache=False)
    assert _topology(module.graph) == _topology(compiled.graph)


def test_exported_router_flow_matches(tmp_path: Path) -> None:
    spec = parse_flowspec(approval_spec("export-hitl"))
    module = _load_module(export_python(spec, get_registry()), tmp_path, "exported_hitl")
    compiled = compile_flow(spec, use_cache=False)
    assert _topology(module.graph) == _topology(compiled.graph)


async def test_exported_graph_runs_under_vanilla_langgraph(tmp_path: Path) -> None:
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
    assert any("Hello from LAB!" in str(v) for v in result.get("ports", {}).values())


def test_secret_refs_become_environ(tmp_path: Path) -> None:
    spec_dict = hello_spec("export-secret")
    # $secret must live in a Secret field (E014); web_search.api_key is one.
    spec_dict["nodes"].append(
        {
            "id": "t",
            "component_id": "lab.tools.web_search",
            "component_version": "1.0.0",
            "config": {"query": "x", "api_key": {"$secret": "my_api_key"}},
            "position": {"x": 0, "y": 0},
        }
    )
    import os

    os.environ["LAB_CRED_MY_API_KEY"] = "sk-test"
    try:
        source = export_python(parse_flowspec(spec_dict), get_registry())
    finally:
        del os.environ["LAB_CRED_MY_API_KEY"]
    # same env var the headless EnvVariablesProvider reads — exported flow and
    # `lab flow run` of the same spec must agree on the name
    assert 'os.environ["LAB_CRED_MY_API_KEY"]' in source


def test_vectorstore_refs_become_handles() -> None:
    spec_dict = hello_spec("export-vs")
    spec_dict["nodes"][1]["config"]["vs"] = {"$vectorstore": "myconn", "collection": "docs"}
    source = export_python(parse_flowspec(spec_dict), get_registry())
    assert "from langgraph_agent_builder.sdk.ports import VectorStoreHandle" in source
    assert "VectorStoreHandle(connection='myconn', collection='docs')" in source
