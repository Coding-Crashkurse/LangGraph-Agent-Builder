"""Langflow parity features (SPEC §18): boot provisioning, priority, limits."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx

from tests.conftest import hello_spec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from fastapi import FastAPI

    from lga.app import AppServices
    from lga.services.settings import Settings


@asynccontextmanager
async def boot_app(
    settings: Settings,
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    """App + lifespan on a dedicated task (same pattern as the conftest fixture)."""
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
        except BaseException as exc:
            failure.append(exc)
            started.set()
            raise

    task = asyncio.get_running_loop().create_task(runner())
    await started.wait()
    if failure:
        raise failure[0]
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=60.0
        ) as client:
            yield application, client
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=15)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()


def _settings(tmp_path: Path, **kwargs: Any) -> Settings:
    from lga.services.settings import Settings

    settings = Settings(home=tmp_path / "lga-home", env="test", **kwargs)
    settings.ensure_dirs()
    return settings


# ---------------------------------------------------------------- starter flows
async def test_starter_flows_seeded_into_empty_db(tmp_path: Path) -> None:
    settings = _settings(tmp_path, create_starter_flows=True)
    async with boot_app(settings) as (_app, client):
        flows = (await client.get("/api/v1/flows")).json()
        slugs = {f["slug"] for f in flows}
        assert {"starter-hello", "starter-approval"} <= slugs
        # drafts only — nothing served
        assert all(f["published_version"] is None for f in flows)


async def test_starter_flows_not_reseeded_when_db_has_flows(tmp_path: Path) -> None:
    settings = _settings(tmp_path, create_starter_flows=True)
    async with boot_app(settings) as (_app, client):
        starter = next(
            f for f in (await client.get("/api/v1/flows")).json() if f["slug"] == "starter-hello"
        )
        await client.delete(f"/api/v1/flows/{starter['id']}")
    async with boot_app(settings) as (_app, client):
        slugs = {f["slug"] for f in (await client.get("/api/v1/flows")).json()}
        assert "starter-hello" not in slugs  # DB not empty → no reseed


# ---------------------------------------------------------------- load flows path
async def test_load_flows_path_with_auto_publish(tmp_path: Path) -> None:
    flows_dir = tmp_path / "provision"
    flows_dir.mkdir()
    (flows_dir / "hello.json").write_text(
        json.dumps(hello_spec("provisioned-flow")), encoding="utf-8"
    )
    (flows_dir / "broken.json").write_text("{not json", encoding="utf-8")
    settings = _settings(
        tmp_path,
        create_starter_flows=False,
        load_flows_path=flows_dir,
        load_flows_publish=True,
    )
    async with boot_app(settings) as (_app, client):
        flows = (await client.get("/api/v1/flows")).json()
        assert [f["slug"] for f in flows] == ["provisioned-flow"]
        assert flows[0]["published_version"] == "0.0.1"
        # auto-published → A2A serves it immediately
        card = await client.get("/a2a/provisioned-flow/.well-known/agent-card.json")
        assert card.status_code == 200


async def test_load_flows_overwrite_flag(tmp_path: Path) -> None:
    flows_dir = tmp_path / "provision"
    flows_dir.mkdir()
    spec = hello_spec("ovw-flow")
    (flows_dir / "flow.json").write_text(json.dumps(spec), encoding="utf-8")
    settings = _settings(tmp_path, create_starter_flows=False, load_flows_path=flows_dir)
    async with boot_app(settings) as (_app, client):
        pass
    # change the file; without overwrite the DB draft must stay untouched
    spec["flow"]["description"] = "CHANGED"
    (flows_dir / "flow.json").write_text(json.dumps(spec), encoding="utf-8")
    async with boot_app(settings) as (_app, client):
        flow = (await client.get("/api/v1/flows")).json()[0]
        assert flow["description"] != "CHANGED"
    settings.load_flows_overwrite = True
    async with boot_app(settings) as (_app, client):
        flow = (await client.get("/api/v1/flows")).json()[0]
        assert flow["description"] == "CHANGED"


# ---------------------------------------------------------------- priority (§18.2)
async def test_priority_in_descriptor(client: httpx.AsyncClient) -> None:
    components = (await client.get("/api/v1/components")).json()
    start = next(c for c in components if c["component_id"] == "lga.io.start")
    assert start["priority"] == 0
    call = next(c for c in components if c["component_id"] == "lga.llm.llm_call")
    agent = next(c for c in components if c["component_id"] == "lga.llm.llm_agent")
    assert call["priority"] < agent["priority"]


# ---------------------------------------------------------------- limits
async def test_max_file_size_env(client: httpx.AsyncClient, svc: AppServices) -> None:
    svc.settings.max_file_size_mb = 0  # everything is too large now
    try:
        response = await client.post(
            "/api/v1/files", files={"file": ("t.txt", b"hello", "text/plain")}
        )
        assert response.status_code == 413
        assert "0 MB" in response.json()["detail"]
    finally:
        svc.settings.max_file_size_mb = 50


async def test_config_exposes_autosave(client: httpx.AsyncClient) -> None:
    config = (await client.get("/api/v1/config")).json()
    assert config["auto_saving"] is True
    assert config["auto_saving_interval_ms"] == 1000
    assert config["max_text_length"] == 300
