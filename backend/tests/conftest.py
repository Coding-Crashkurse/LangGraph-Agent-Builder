"""Test fixtures: in-memory app with ASGI client; runtime API always mocked.

Backend unit tests never touch the network — the agentplane runtime API is
mocked via respx (CLAUDE.md testing rules).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from langgraph_agent_builder.app import create_app
from langgraph_agent_builder.services.settings import Settings

RUNTIME_URL = "http://runtime.test"

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples"
SCHEMA_PATH = REPO_ROOT / "schemas" / "flow-definition.schema.json"


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "home": tmp_path,
        "database_url": f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        **overrides,
    }
    return Settings(**values)


ClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


@pytest.fixture
def make_client(tmp_path: Path) -> ClientFactory:
    """Factory: spin up the app (with lifespan) and yield an ASGI client."""

    @asynccontextmanager
    async def factory(**settings_overrides: Any) -> AsyncIterator[AsyncClient]:
        settings = make_settings(tmp_path, **settings_overrides)
        app = create_app(settings, backend_only=True)
        async with (
            LifespanManager(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            yield client

    return factory


@pytest.fixture
async def client(make_client: ClientFactory) -> AsyncIterator[AsyncClient]:
    """Default client: no runtime configured, auth_mode=none."""
    async with make_client() as c:
        yield c


@pytest.fixture
async def runtime_client(make_client: ClientFactory) -> AsyncIterator[AsyncClient]:
    """Client with a (mocked) runtime configured and a static forwarded token."""
    async with make_client(runtime_url=RUNTIME_URL, runtime_token="dev-token") as c:
        yield c


def definition(**overrides: Any) -> dict[str, Any]:
    """A small valid FlowDefinition (start → llm_call → end)."""
    base: dict[str, Any] = {
        "schema_version": 1,
        "name": "hello-agent",
        "display_name": "Hello Agent",
        "description": "test flow",
        "tags": ["demo"],
        "expose": {"kind": "a2a"},
        "nodes": [
            {
                "id": "start_1",
                "type": "start",
                "version": 1,
                "config": {
                    "input_schema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    }
                },
            },
            {
                "id": "call_1",
                "type": "llm_call",
                "version": 1,
                "config": {"resource": "default-llm", "prompt": "{message}"},
            },
            {
                "id": "end_1",
                "type": "end",
                "version": 1,
                "config": {"output_from": "call_1.text"},
            },
        ],
        "edges": [
            {"from": "start_1.message", "to": "call_1.message"},
            {"from": "call_1.text", "to": "end_1.input"},
        ],
        "layout": {"nodes": {"start_1": {"x": 0, "y": 0}}},
    }
    base.update(overrides)
    return base


def definition_info(name: str = "hello-agent", **overrides: Any) -> dict[str, Any]:
    """A DefinitionInfo payload as the runtime would return it."""
    payload: dict[str, Any] = {
        "name": name,
        "display_name": "",
        "description": "",
        "tags": [],
        "expose_kind": "a2a",
        "status": "draft",
        "latest_version": None,
        "deployed_version": None,
        "endpoint_url": None,
        "owner": "tester",
        "created_at": "2026-07-12T10:00:00Z",
        "updated_at": "2026-07-12T10:00:00Z",
        "definition": None,
    }
    payload.update(overrides)
    return payload


def read_example(name: str) -> str:
    return (EXAMPLES_DIR / name).read_text(encoding="utf-8")
