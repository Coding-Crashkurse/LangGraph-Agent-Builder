import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import load_flow, validate_ok  # noqa: E402

HERE = Path(__file__).parent


def test_validates_clean():
    validate_ok(load_flow(HERE))


def test_headless_script_end_to_end(tmp_path):
    result = subprocess.run(
        [sys.executable, str(HERE / "main.py")], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert "vanilla result: Headless says hello." in result.stdout
    assert "runtime result: completed" in result.stdout
    exported = HERE / "exported_flow.py"
    assert exported.exists()
    run = subprocess.run(
        [sys.executable, str(exported)], capture_output=True, text=True, timeout=120
    )
    assert run.returncode == 0, run.stderr
    assert "Headless says hello." in run.stdout
    exported.unlink()  # generated artifact, not checked in
