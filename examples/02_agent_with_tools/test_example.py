import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import load_flow, run_local, validate_ok  # noqa: E402

HERE = Path(__file__).parent


def test_validates_and_binds_tools():
    from lga.compiler import compile_flow

    spec = load_flow(HERE)
    validate_ok(spec)
    compiled = compile_flow(spec, use_cache=False)
    assert sorted(compiled.report.tool_bindings.get("agent", [])) == [
        "calculator",
        "http_request",
    ]
    # tool providers are not graph nodes
    assert "calc" not in compiled.graph.get_graph().nodes


def test_agent_completes_with_fake_model():
    result = run_local(load_flow(HERE), input_text="what is (2+3)*4?")
    assert result.status == "completed"
    assert "tools" in result.result_text
