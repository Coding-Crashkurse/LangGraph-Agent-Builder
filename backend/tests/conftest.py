"""Shared fixtures: tiered settings (SQLite always, Postgres when reachable),
in-process app with lifespan, ASGI http client, canonical flow specs."""

from __future__ import annotations

import asyncio
import socket
import sys
import uuid
from typing import Any

import httpx
import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

POSTGRES_HOST, POSTGRES_PORT = "localhost", 55432
POSTGRES_ADMIN_URL = "postgresql+asyncpg://graphforge:graphforge@localhost:55432/graphforge"


def _postgres_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((POSTGRES_HOST, POSTGRES_PORT)) == 0


PG_AVAILABLE = _postgres_available()
TIERS = ["sqlite", "postgres"] if PG_AVAILABLE else ["sqlite"]


async def _ensure_pg_database(name: str) -> str:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(POSTGRES_ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        exists = await conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
        )
        if exists.scalar() is None:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()
    return f"postgresql+asyncpg://graphforge:graphforge@localhost:55432/{name}"


@pytest.fixture(params=TIERS)
async def settings(request, tmp_path):
    """Fresh Settings per test; postgres tier gets its own throwaway database."""
    from lga.services.settings import Settings

    kwargs: dict[str, Any] = {
        "home": tmp_path / "lga-home",
        "env": "test",
        "create_starter_flows": False,  # keep test DBs empty (see test_langflow_parity)
    }
    if request.param == "postgres":
        db = f"lga_test_{uuid.uuid4().hex[:10]}"
        kwargs["database_url"] = await _ensure_pg_database(db)
    settings = Settings(**kwargs)
    settings.ensure_dirs()
    yield settings


@pytest.fixture
async def sqlite_settings(tmp_path):
    from lga.services.settings import Settings

    settings = Settings(home=tmp_path / "lga-home", env="test", create_starter_flows=False)
    settings.ensure_dirs()
    return settings


@pytest.fixture
async def app(settings):
    """Full FastAPI app with lifespan running (backend-only).

    The lifespan is driven by ONE dedicated task: pytest-asyncio tears fixtures
    down in a different task, which anyio cancel scopes (MCP session manager)
    reject.
    """
    from lga.app import create_app
    from lga.db.migrate import upgrade_async

    await upgrade_async(settings)
    application = create_app(settings, backend_only=True)
    application.state.auto_migrate = False

    started: asyncio.Event = asyncio.Event()
    stop: asyncio.Event = asyncio.Event()
    failure: list[BaseException] = []

    async def runner() -> None:
        try:
            async with application.router.lifespan_context(application):
                started.set()
                await stop.wait()
        except BaseException as exc:  # surface startup errors to the test
            failure.append(exc)
            started.set()
            raise

    task = asyncio.get_running_loop().create_task(runner())
    await started.wait()
    if failure:
        raise failure[0]
    try:
        yield application
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=15)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=60.0
    ) as http_client:
        yield http_client


@pytest.fixture
def svc(app):
    return app.state.svc


# --------------------------------------------------------------------- specs
def hello_spec(slug: str = "hello", **flow_extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "flow": {
            "name": slug,
            "slug": slug,
            "description": "test flow",
            "a2a": {"enabled": True, "description": "Scripted greeting.", "examples": ["hi"]},
            **flow_extra,
        },
        "nodes": [
            {
                "id": "start",
                "component_id": "lga.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "fake",
                "component_id": "lga.testing.fake_llm",
                "component_version": "1.0.0",
                "config": {"replies": ["Hello from LGA!"]},
                "position": {"x": 300, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lga.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 600, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "fake", "input": "input"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "fake", "output": "message"},
                "target": {"node": "end", "input": "message"},
            },
        ],
    }


def approval_spec(slug: str = "hitl") -> dict[str, Any]:
    return {
        "schema_version": "1",
        "flow": {
            "name": slug,
            "slug": slug,
            "description": "hitl flow",
            "a2a": {
                "enabled": True,
                "description": "Approval flow.",
                "examples": ["please approve"],
            },
        },
        "nodes": [
            {
                "id": "start",
                "component_id": "lga.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "fake",
                "component_id": "lga.testing.fake_llm",
                "component_version": "1.0.0",
                "config": {"replies": ["draft answer", "revised answer"]},
                "position": {"x": 200, "y": 0},
            },
            {
                "id": "review",
                "component_id": "lga.flow.human_approval",
                "component_version": "1.0.0",
                "config": {"prompt": "Release this answer?"},
                "position": {"x": 400, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lga.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 600, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "fake", "input": "input"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "fake", "output": "message"},
                "target": {"node": "review", "input": "input"},
            },
            {
                "id": "e3",
                "kind": "router",
                "source": {"node": "review", "output": "approve"},
                "target": {"node": "end", "input": "message"},
            },
            {
                "id": "e4",
                "kind": "router",
                "source": {"node": "review", "output": "reject"},
                "target": {"node": "fake", "input": "input"},
            },
        ],
    }


def slow_spec(slug: str = "slow", seconds: float = 10.0) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "flow": {
            "name": slug,
            "slug": slug,
            "description": "slow flow",
            "a2a": {"enabled": True, "description": "Sleeps.", "examples": ["zzz"]},
        },
        "nodes": [
            {
                "id": "start",
                "component_id": "lga.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "slow",
                "component_id": "lga.testing.slow_node",
                "component_version": "1.0.0",
                "config": {"seconds": seconds},
                "position": {"x": 300, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lga.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 600, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "slow", "input": "input"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "slow", "output": "message"},
                "target": {"node": "end", "input": "message"},
            },
        ],
    }


async def create_and_publish(client: httpx.AsyncClient, spec: dict[str, Any]) -> str:
    response = await client.post("/api/v1/flows", json={"spec": spec})
    assert response.status_code == 201, response.text
    flow_id = response.json()["id"]
    response = await client.post(f"/api/v1/flows/{flow_id}/publish", json={"version": "minor"})
    assert response.status_code == 200 and response.json()["published"], response.text
    return flow_id
