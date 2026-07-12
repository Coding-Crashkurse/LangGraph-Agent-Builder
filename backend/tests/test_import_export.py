"""Share/Import — canonical FlowDefinition YAML, round-trip safe (SPEC §3, §5)."""

from __future__ import annotations

import yaml
from httpx import AsyncClient

from tests.conftest import definition, read_example


async def test_export_yaml_roundtrips_through_import(client: AsyncClient) -> None:
    await client.post("/api/v1/flows", json=definition())
    exported = await client.get("/api/v1/flows/hello-agent/export")
    assert exported.status_code == 200
    assert 'filename="hello-agent.flow.yaml"' in exported.headers["content-disposition"]

    await client.delete("/api/v1/flows/hello-agent")
    imported = await client.post(
        "/api/v1/flows/import",
        content=exported.text,
        headers={"content-type": "application/yaml"},
    )
    assert imported.status_code == 201
    fetched = await client.get("/api/v1/flows/hello-agent")
    assert yaml.safe_load(exported.text) == fetched.json()["definition"]


async def test_export_is_deterministic(client: AsyncClient) -> None:
    await client.post("/api/v1/flows", json=definition())
    first = (await client.get("/api/v1/flows/hello-agent/export")).text
    second = (await client.get("/api/v1/flows/hello-agent/export")).text
    assert first == second


async def test_export_json_format(client: AsyncClient) -> None:
    await client.post("/api/v1/flows", json=definition())
    exported = await client.get("/api/v1/flows/hello-agent/export", params={"format": "json"})
    assert exported.headers["content-type"].startswith("application/json")
    assert exported.json()["name"] == "hello-agent"


async def test_import_conflict_without_overwrite(client: AsyncClient) -> None:
    await client.post("/api/v1/flows", json=definition())
    text = read_example("hello-agent.flow.yaml").replace("name: hello-agent", "name: hello-agent")
    conflict = await client.post(
        "/api/v1/flows/import", content=text, headers={"content-type": "application/yaml"}
    )
    assert conflict.status_code == 409

    replaced = await client.post(
        "/api/v1/flows/import",
        params={"overwrite": "true"},
        content=text,
        headers={"content-type": "application/yaml"},
    )
    assert replaced.status_code == 201
    assert replaced.json() == {"name": "hello-agent", "created": False}


async def test_import_rejects_non_mapping(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/flows/import", content="- 1\n- 2\n", headers={"content-type": "application/yaml"}
    )
    assert resp.status_code == 422


async def test_import_all_examples(client: AsyncClient) -> None:
    """Every shipped example imports cleanly (git-safe, no secrets, parseable)."""
    from tests.conftest import EXAMPLES_DIR

    for path in sorted(EXAMPLES_DIR.glob("*.flow.yaml")):
        resp = await client.post(
            "/api/v1/flows/import",
            content=path.read_text(encoding="utf-8"),
            headers={"content-type": "application/yaml"},
        )
        assert resp.status_code == 201, f"{path.name}: {resp.text}"
