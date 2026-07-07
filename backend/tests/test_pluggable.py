"""Pluggable task store (LGA_A2A_TASK_STORE) + slug-based flow API endpoint."""

from __future__ import annotations

import pytest

from lga.a2a.tasks import DbTaskStore, resolve_task_store
from tests.conftest import create_and_publish, hello_spec


# ---------------------------------------------------------------- store resolution
def _fake_sessions():
    return None  # not touched by memory/custom stores in this test


def test_resolve_db_default(sqlite_settings):
    store = resolve_task_store("db", sessions=_fake_sessions(), flow_slug="s")
    assert isinstance(store, DbTaskStore)
    assert isinstance(resolve_task_store("", sessions=_fake_sessions(), flow_slug="s"), DbTaskStore)


def test_resolve_memory():
    from a2a.server.tasks import InMemoryTaskStore

    store = resolve_task_store("memory", sessions=_fake_sessions(), flow_slug="s")
    assert isinstance(store, InMemoryTaskStore)


def custom_store_factory(*, sessions, flow_slug, settings=None):
    from a2a.server.tasks import InMemoryTaskStore

    store = InMemoryTaskStore()
    store.flow_slug = flow_slug  # type: ignore[attr-defined]
    return store


def test_resolve_custom_dotted_path():
    store = resolve_task_store(
        "tests.test_pluggable:custom_store_factory",
        sessions=_fake_sessions(),
        flow_slug="my-flow",
    )
    assert getattr(store, "flow_slug", None) == "my-flow"


def test_resolve_rejects_garbage():
    with pytest.raises(ValueError):
        resolve_task_store("not-a-mode", sessions=_fake_sessions(), flow_slug="s")


# ---------------------------------------------------------------- memory store end-to-end
async def test_memory_task_store_serves_a2a(client, svc):
    svc.settings.a2a_task_store = "memory"
    try:
        await create_and_publish(client, hello_spec("mem-store-flow"))
        response = await client.post(
            "/a2a/mem-store-flow/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "messageId": "m-mem-1",
                        "parts": [{"kind": "text", "text": "hi"}],
                    }
                },
            },
        )
        task = response.json()["result"]
        assert task["status"]["state"] == "completed"
    finally:
        svc.settings.a2a_task_store = "db"
        await svc.remount()


# ---------------------------------------------------------------- slug-based API (§9.3)
async def test_run_by_slug_base_url(client):
    await create_and_publish(client, hello_spec("slug-api-flow"))
    response = await client.post(
        "/api/v1/flows/slug-api-flow/run",
        json={"input_text": "hi", "stream": False},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["result_text"] == "Hello from LGA!"


# ---------------------------------------------------------------- run trace deletion
async def test_delete_single_run_trace(client):
    await create_and_publish(client, hello_spec("trace-flow"))
    run = (
        await client.post(
            "/api/v1/flows/trace-flow/run", json={"input_text": "hi", "stream": False}
        )
    ).json()
    run_id = run["run_id"]
    assert (await client.get(f"/api/v1/runs/{run_id}")).status_code == 200
    assert (await client.delete(f"/api/v1/runs/{run_id}")).status_code == 204
    assert (await client.get(f"/api/v1/runs/{run_id}")).status_code == 404
    # events are gone with the trace
    assert (await client.delete(f"/api/v1/runs/{run_id}")).status_code == 404


async def test_clear_finished_runs(client):
    await create_and_publish(client, hello_spec("clear-flow"))
    for _ in range(3):
        await client.post(
            "/api/v1/flows/clear-flow/run", json={"input_text": "hi", "stream": False}
        )
    response = await client.delete("/api/v1/runs")
    assert response.json()["deleted"] >= 3
    assert (await client.get("/api/v1/runs")).json() == []
