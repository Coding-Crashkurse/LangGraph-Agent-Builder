import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import load_flow, run_local, validate_ok  # noqa: E402

HERE = Path(__file__).parent


def test_validates_clean():
    validate_ok(load_flow(HERE))


def test_bug_branch():
    result = run_local(load_flow(HERE), input_text="I found a bug in the export")
    assert result.status == "completed"
    assert "BUG" in result.result_text


def test_billing_branch():
    result = run_local(load_flow(HERE), input_text="question about billing")
    assert "BILLING" in result.result_text


def test_rule_router_fallback_urgent():
    result = run_local(load_flow(HERE), input_text="something else, need it asap")
    assert "URGENT" in result.result_text


def test_rule_router_fallback_normal():
    result = run_local(load_flow(HERE), input_text="just wondering about things")
    assert "NORMAL" in result.result_text
