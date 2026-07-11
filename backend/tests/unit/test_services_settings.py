"""Unit tests for langgraph_agent_builder.services.settings (SPEC §14): URL normalization, derived
defaults, secret-key resolution, component dirs, and env vectorstore descriptors."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from langgraph_agent_builder.services.settings import Settings, get_settings, new_api_key

if TYPE_CHECKING:
    from pathlib import Path


def _mk(tmp_path: Path, **kw: object) -> Settings:
    return Settings(home=tmp_path / "home", env="test", **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------- URL normalization
def test_sqlite_defaults_and_flags(tmp_path: Path) -> None:
    settings = _mk(tmp_path)
    assert settings.is_sqlite is True
    assert settings.is_postgres is False
    assert settings.storage_tier == "sqlite"
    assert settings.async_database_url.startswith("sqlite+aiosqlite:///")
    assert settings.sqlite_db_path.name == "langgraph_agent_builder.db"


def test_sqlite_plain_scheme_is_upgraded_to_aiosqlite(tmp_path: Path) -> None:
    settings = _mk(tmp_path, database_url="sqlite:///" + (tmp_path / "x.db").as_posix())
    assert settings.async_database_url.startswith("sqlite+aiosqlite:///")


def test_postgres_url_normalization(tmp_path: Path) -> None:
    settings = _mk(tmp_path, database_url="postgresql://u:p@h:55432/db")
    assert settings.is_postgres is True
    assert settings.storage_tier == "postgres"
    assert settings.async_database_url == "postgresql+asyncpg://u:p@h:55432/db"
    assert settings.psycopg_dsn == "postgresql://u:p@h:55432/db"


def test_postgres_psycopg_scheme_is_normalized(tmp_path: Path) -> None:
    settings = _mk(tmp_path, database_url="postgresql+psycopg://u:p@h/db")
    assert settings.is_postgres is True
    assert settings.async_database_url == "postgresql+asyncpg://u:p@h/db"
    assert settings.psycopg_dsn == "postgresql://u:p@h/db"


def test_already_async_url_passes_through(tmp_path: Path) -> None:
    url = "postgresql+asyncpg://u:p@h/db"
    settings = _mk(tmp_path, database_url=url)
    assert settings.async_database_url == url


# --------------------------------------------------------------------- derived defaults
def test_fill_defaults_dev_auth_off(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "h", env="dev")
    assert settings.auth_enabled is False
    assert settings.host_url == f"http://{settings.host}:{settings.port}"
    assert settings.files_dir == settings.home / "files"


def test_fill_defaults_prod_auth_on(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "h", env="prod")
    assert settings.auth_enabled is True


def test_explicit_host_url_and_auth_preserved(tmp_path: Path) -> None:
    settings = _mk(tmp_path, host_url="https://public.example", auth_enabled=True)
    assert settings.host_url == "https://public.example"
    assert settings.auth_enabled is True


def test_home_is_expanded(tmp_path: Path) -> None:
    settings = _mk(tmp_path)
    assert "~" not in str(settings.home)


def test_vectors_dir_under_home(tmp_path: Path) -> None:
    settings = _mk(tmp_path)
    assert settings.vectors_dir == settings.home / "vectors"


# --------------------------------------------------------------------- secret key
def test_resolve_secret_key_returns_explicit(tmp_path: Path) -> None:
    settings = _mk(tmp_path, secret_key="already-set")
    assert settings.resolve_secret_key() == "already-set"


def test_resolve_secret_key_prod_requires_key(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "h", env="prod")
    with pytest.raises(RuntimeError, match="LAB_SECRET_KEY"):
        settings.resolve_secret_key()


def test_resolve_secret_key_generates_and_persists(tmp_path: Path) -> None:
    settings = _mk(tmp_path)
    settings.ensure_dirs()
    first = settings.resolve_secret_key()
    assert first
    assert (settings.home / "secret_key").read_text(encoding="utf-8").strip() == first
    # a fresh Settings on the same home reads the persisted key
    settings.secret_key = ""
    second = settings.resolve_secret_key()
    assert second == first


# --------------------------------------------------------------------- component dirs
def test_component_dirs_empty(tmp_path: Path) -> None:
    assert _mk(tmp_path).component_dirs() == []


def test_component_dirs_splits_pathsep(tmp_path: Path) -> None:
    import os

    a, b = tmp_path / "a", tmp_path / "b"
    settings = _mk(tmp_path, components_path=os.pathsep.join([str(a), str(b), ""]))
    dirs = settings.component_dirs()
    assert dirs == [a, b]  # trailing empty entry dropped


# --------------------------------------------------------------------- env vectorstores
def test_vectorstore_env_connections_parses_valid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_VECTORSTORE_PROD_DB", '{"backend": "qdrant", "url": "http://q"}')
    monkeypatch.setenv("LAB_VECTORSTORE_BAD", "{not json")
    monkeypatch.setenv("LAB_UNRELATED", "ignored")
    conns = _mk(tmp_path).vectorstore_env_connections()
    assert conns["prod-db"] == {"backend": "qdrant", "url": "http://q"}
    assert "bad" not in conns  # invalid JSON silently skipped
    assert "unrelated" not in conns


# --------------------------------------------------------------------- misc helpers
def test_new_api_key_prefix_and_uniqueness() -> None:
    a, b = new_api_key(), new_api_key()
    assert a.startswith("lab_sk_")
    assert a != b


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_ensure_dirs_creates_all(tmp_path: Path) -> None:
    settings = _mk(tmp_path)
    settings.ensure_dirs()
    assert settings.home.is_dir()
    assert settings.files_dir is not None
    assert settings.files_dir.is_dir()
    assert settings.vectors_dir.is_dir()
