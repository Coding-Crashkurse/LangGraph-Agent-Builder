"""Unit tests for db.migrate — URL rewriting, config, offline SQL, upgrade."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from langgraph_agent_builder.db.migrate import (
    MIGRATIONS_DIR,
    build_config,
    sync_url,
    upgrade,
    upgrade_async,
)
from langgraph_agent_builder.services.settings import Settings


def _sqlite_settings(tmp_path: Path) -> Settings:
    settings = Settings(home=tmp_path / "home", env="test", create_starter_flows=False)
    settings.ensure_dirs()
    return settings


def test_sync_url_rewrites_sqlite_async_to_sync(tmp_path: Path) -> None:
    settings = _sqlite_settings(tmp_path)
    url = sync_url(settings)
    assert url.startswith("sqlite:///")
    assert "aiosqlite" not in url


def test_sync_url_rewrites_postgres_asyncpg_to_psycopg() -> None:
    settings = Settings(
        home=Path("/tmp/x"),
        env="test",
        database_url="postgresql+asyncpg://u:p@localhost:55432/db",
        create_starter_flows=False,
    )
    assert sync_url(settings) == "postgresql+psycopg://u:p@localhost:55432/db"


def test_build_config_points_at_shipped_migrations(tmp_path: Path) -> None:
    settings = _sqlite_settings(tmp_path)
    cfg = build_config(settings)
    assert cfg.get_main_option("script_location") == str(MIGRATIONS_DIR)
    assert cfg.get_main_option("sqlalchemy.url") == sync_url(settings)


def test_upgrade_creates_sqlite_database(tmp_path: Path) -> None:
    settings = _sqlite_settings(tmp_path)
    assert not settings.sqlite_db_path.exists()
    upgrade(settings)
    assert settings.sqlite_db_path.exists()


async def test_upgrade_async_runs_migrations_in_thread(tmp_path: Path) -> None:
    settings = _sqlite_settings(tmp_path)
    await upgrade_async(settings)
    assert settings.sqlite_db_path.exists()


def _runs_columns(settings: Settings) -> set[str]:
    engine = sa.create_engine(sync_url(settings))
    try:
        with engine.connect() as conn:
            return {c["name"] for c in sa.inspect(conn).get_columns("runs")}
    finally:
        engine.dispose()


def test_upgrade_head_creates_runs_node_id(tmp_path: Path) -> None:
    settings = _sqlite_settings(tmp_path)
    upgrade(settings)
    assert "node_id" in _runs_columns(settings)


def test_0003_adds_node_id_to_pre_existing_runs_table(tmp_path: Path) -> None:
    """0002→0003 on a v2-era database (runs without node_id) adds the column.

    A fresh 0001 baseline mirrors the current models (node_id included), so the
    old shape is simulated by dropping the column before stepping to head.
    """
    settings = _sqlite_settings(tmp_path)
    upgrade(settings, "0002")
    engine = sa.create_engine(sync_url(settings))
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("ALTER TABLE runs DROP COLUMN node_id"))
    finally:
        engine.dispose()
    assert "node_id" not in _runs_columns(settings)
    upgrade(settings)  # 0002 → 0003
    assert "node_id" in _runs_columns(settings)
