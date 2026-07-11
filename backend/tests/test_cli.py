"""CLI suite (SPEC §15.6): version/init/validate/component/apikey/config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lga.cli.main import app
from tests.conftest import hello_spec

runner = CliRunner()


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LGA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("LGA_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_version_json(cli_env: Path) -> None:
    result = runner.invoke(app, ["version", "--json"])
    assert result.exit_code == 0, result.output
    info = json.loads(result.output)
    assert info["lga"]
    assert info["langgraph"]
    assert info["db_backend"] == "sqlite"


def test_init_scaffolds_workspace(cli_env: Path) -> None:
    result = runner.invoke(app, ["init", "ws"])
    assert result.exit_code == 0, result.output
    ws = cli_env / "ws"
    assert (ws / ".env").exists()
    assert (ws / "components" / "data" / "shout.py").exists()
    assert (ws / "flows").is_dir()
    assert (ws / ".gitignore").exists()
    # re-init without --force refuses
    result = runner.invoke(app, ["init", "ws"])
    assert result.exit_code == 2
    result = runner.invoke(app, ["init", "ws", "--force"])
    assert result.exit_code == 0


def test_flow_validate_exit_codes(cli_env: Path) -> None:
    good = cli_env / "good.json"
    good.write_text(json.dumps(hello_spec("cli-good")), encoding="utf-8")
    result = runner.invoke(app, ["flow", "validate", str(good)])
    assert result.exit_code == 0, result.output

    bad_spec = hello_spec("cli-bad")
    bad_spec["nodes"][1]["component_id"] = "lga.missing.nope"
    bad = cli_env / "bad.json"
    bad.write_text(json.dumps(bad_spec), encoding="utf-8")
    result = runner.invoke(app, ["flow", "validate", str(bad)])
    assert result.exit_code == 3  # ERROR diagnostics → exit 3 (CI contract)
    assert "E002" in result.output

    result = runner.invoke(app, ["flow", "validate", str(bad), "--format", "json"])
    assert result.exit_code == 3
    diags = json.loads(result.output)
    assert any(d["code"] == "E002" for d in diags)


def test_flow_run_local(cli_env: Path) -> None:
    flow = cli_env / "flow.json"
    flow.write_text(json.dumps(hello_spec("cli-run")), encoding="utf-8")
    result = runner.invoke(app, ["flow", "run", str(flow), "--local", "--input", "hi"])
    assert result.exit_code == 0, result.output
    assert "Hello from LGA!" in result.output


def test_component_new_scaffold(cli_env: Path) -> None:
    result = runner.invoke(app, ["component", "new", "my_widget", "--category", "data"])
    assert result.exit_code == 0, result.output
    pkg = cli_env / "components" / "lga_my_widget"
    pyproject = (pkg / "pyproject.toml").read_text(encoding="utf-8")
    assert '[project.entry-points."lga.components"]' in pyproject
    # the generated async test must be runnable out of the box
    assert "pytest-asyncio" in pyproject
    assert 'asyncio_mode = "auto"' in pyproject
    source = (pkg / "src" / "lga_my_widget" / "__init__.py").read_text(encoding="utf-8")
    assert "class MyWidget(Component)" in source
    assert (pkg / "tests" / "test_my_widget.py").exists()


def test_apikey_lifecycle_headless(cli_env: Path) -> None:
    result = runner.invoke(
        app, ["apikey", "create", "--scopes", "a2a:invoke", "--name", "ci", "--json"]
    )
    assert result.exit_code == 0, result.output
    created = json.loads(result.output)
    assert created["key"].startswith("lga_sk_")
    result = runner.invoke(app, ["apikey", "list", "--json"])
    keys = json.loads(result.output)
    assert any(k["id"] == created["id"] for k in keys)
    result = runner.invoke(app, ["apikey", "revoke", created["id"]])
    assert result.exit_code == 0


def test_config_masks_secret(cli_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LGA_SECRET_KEY", "super-secret-value")
    result = runner.invoke(app, ["config", "--json"])
    assert result.exit_code == 0
    rows = json.loads(result.output)
    secret_row = next(r for r in rows if r["key"] == "LGA_SECRET_KEY")
    assert secret_row["value"] == "***"
    assert secret_row["source"] == "env/.env"


def test_migrate_creates_schema(cli_env: Path) -> None:
    result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 0, result.output
    assert (Path(cli_env) / "home" / "lga.db").exists()
