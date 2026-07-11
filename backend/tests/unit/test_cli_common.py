"""Unit tests for cli._common — env-file precedence + exit codes (SPEC §2.6)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from langgraph_agent_builder.cli._common import (
    EXIT_USAGE,
    build_settings,
    ensure_selector_policy,
    load_env_files,
    run_async,
)


def test_load_env_files_missing_file_exits_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no ./.env present
    with pytest.raises(SystemExit) as excinfo:
        load_env_files(tmp_path / "does-not-exist.env")
    assert excinfo.value.code == EXIT_USAGE


def test_load_env_files_loads_provided_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LAB_TEST_MARKER_VAR", raising=False)
    env_file = tmp_path / "custom.env"
    env_file.write_text("LAB_TEST_MARKER_VAR=from_env_file\n", encoding="utf-8")
    load_env_files(env_file)
    assert os.environ["LAB_TEST_MARKER_VAR"] == "from_env_file"
    monkeypatch.delenv("LAB_TEST_MARKER_VAR", raising=False)


def test_load_env_files_none_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # only ./.env attempted, which is absent → no error
    load_env_files(None)


def test_build_settings_drops_none_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LAB_PORT", raising=False)
    settings = build_settings(env_file=None, host="0.0.0.0", port=None, log_level=None)
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000  # None override dropped → default kept


def test_ensure_selector_policy_on_windows() -> None:
    ensure_selector_policy()
    import sys

    if sys.platform == "win32":
        policy = asyncio.get_event_loop_policy()
        assert isinstance(policy, asyncio.WindowsSelectorEventLoopPolicy)


def test_run_async_returns_coroutine_result() -> None:
    async def compute() -> int:
        await asyncio.sleep(0)
        return 42

    assert run_async(compute()) == 42
