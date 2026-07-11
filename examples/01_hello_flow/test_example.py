import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import load_flow, run_local, validate_ok  # noqa: E402

HERE = Path(__file__).parent


def test_validates_clean():
    validate_ok(load_flow(HERE))


def test_runs_and_greets():
    result = run_local(load_flow(HERE), input_text="hi")
    assert result.status == "completed"
    assert result.result_text == "Hello from LAB!"
