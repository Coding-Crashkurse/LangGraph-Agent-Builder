"""Flows & versions REST API (SPEC §9.1): CRUD lifecycle, publish/versions/
rollback, validate, export (json + python), lock, node-upgrade, and the
404/409/422 error branches."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.conftest import hello_spec

if TYPE_CHECKING:
    import httpx


def _bad_spec() -> dict[str, Any]:
    """Structurally invalid: an unsupported schema_version → FlowSpecError."""
    return {"schema_version": "9", "flow": {"name": "x", "slug": "x"}, "nodes": [], "edges": []}


def _unrunnable_spec(slug: str = "broken") -> dict[str, Any]:
    """Parses fine, but references a component that does not exist → compile errors."""
    return {
        "schema_version": "1",
        "flow": {"name": slug, "slug": slug},
        "nodes": [
            {"id": "start", "component_id": "lab.io.start", "config": {}},
            {"id": "ghost", "component_id": "lab.does.not.exist", "config": {}},
            {"id": "end", "component_id": "lab.io.end", "config": {}},
        ],
        "edges": [],
    }


# ----------------------------------------------------------------- create / read
async def test_create_list_get_by_id_and_slug(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/flows", json={"spec": hello_spec("crud")})
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["slug"] == "crud"
    assert created["published_version"] is None  # fresh draft, never published
    flow_id = created["id"]

    listed = await client.get("/api/v1/flows")
    assert listed.status_code == 200
    assert any(f["id"] == flow_id for f in listed.json())

    by_id = await client.get(f"/api/v1/flows/{flow_id}")
    by_slug = await client.get("/api/v1/flows/crud")
    assert by_id.status_code == by_slug.status_code == 200
    assert by_id.json()["id"] == by_slug.json()["id"] == flow_id


async def test_get_unknown_flow_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/flows/no-such-flow")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "flow not found"


async def test_create_invalid_spec_is_422(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/flows", json={"spec": _bad_spec()})
    assert resp.status_code == 422
    assert "invalid FlowSpec" in resp.json()["detail"]


async def test_create_duplicate_slug_is_409(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/v1/flows", json={"spec": hello_spec("dup")})).status_code == 201
    resp = await client.post("/api/v1/flows", json={"spec": hello_spec("dup")})
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


# ------------------------------------------------------------------------ update
async def test_update_flow_success(client: httpx.AsyncClient) -> None:
    created = (await client.post("/api/v1/flows", json={"spec": hello_spec("edit")})).json()
    spec = hello_spec("edit")
    spec["flow"]["description"] = "changed description"
    resp = await client.patch(f"/api/v1/flows/{created['id']}", json={"spec": spec})
    assert resp.status_code == 200
    assert resp.json()["description"] == "changed description"


async def test_update_unknown_flow_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/api/v1/flows/ghost", json={"spec": hello_spec("ghost")})
    assert resp.status_code == 404


async def test_update_invalid_spec_is_422(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/flows", json={"spec": hello_spec("edit2")})
    resp = await client.patch("/api/v1/flows/edit2", json={"spec": _bad_spec()})
    assert resp.status_code == 422
    assert "invalid FlowSpec" in resp.json()["detail"]


async def test_update_to_taken_slug_is_409(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/flows", json={"spec": hello_spec("taken")})
    other = (await client.post("/api/v1/flows", json={"spec": hello_spec("mover")})).json()
    # rename "mover" onto the existing "taken" slug → conflict
    resp = await client.patch(f"/api/v1/flows/{other['id']}", json={"spec": hello_spec("taken")})
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


# ----------------------------------------------------------------- list filters
async def test_list_flows_pagination(client: httpx.AsyncClient) -> None:
    for slug in ("pag-a", "pag-b", "pag-c"):
        assert (
            await client.post("/api/v1/flows", json={"spec": hello_spec(slug)})
        ).status_code == 201
    page = (await client.get("/api/v1/flows", params={"limit": 2})).json()
    assert len(page) == 2
    rest = (await client.get("/api/v1/flows", params={"limit": 2, "offset": 2})).json()
    assert len(rest) == 1
    assert {f["id"] for f in page}.isdisjoint({f["id"] for f in rest})


async def test_list_filters_by_tag_and_query(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/flows", json={"spec": hello_spec("alpha", tags=["greeting"])})
    await client.post("/api/v1/flows", json={"spec": hello_spec("beta", tags=["other"])})

    tagged = await client.get("/api/v1/flows", params={"tag": "greeting"})
    slugs = {f["slug"] for f in tagged.json()}
    assert "alpha" in slugs
    assert "beta" not in slugs  # filtered out by tag mismatch

    searched = await client.get("/api/v1/flows", params={"q": "BET"})
    found = {f["slug"] for f in searched.json()}
    assert found == {"beta"}  # case-insensitive slug/name match, alpha excluded


# ------------------------------------------------------------ lock / delete
async def test_lock_blocks_update_then_delete(client: httpx.AsyncClient) -> None:
    created = (await client.post("/api/v1/flows", json={"spec": hello_spec("locked")})).json()
    locked = await client.post("/api/v1/flows/locked/lock", json={"locked": True})
    assert locked.status_code == 200
    assert locked.json()["locked"] is True

    blocked = await client.patch("/api/v1/flows/locked", json={"spec": hello_spec("locked")})
    assert blocked.status_code == 409
    assert "locked" in blocked.json()["detail"]

    await client.post("/api/v1/flows/locked/lock", json={"locked": False})
    deleted = await client.delete(f"/api/v1/flows/{created['id']}")
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/flows/locked")).status_code == 404


# ----------------------------------------------------------- validate / upgrade
async def test_validate_flow_reports_no_errors_for_runnable(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/flows", json={"spec": hello_spec("valid")})
    resp = await client.post("/api/v1/flows/valid/validate", params={"deep": "false"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["compile_report"] is not None  # compiled cleanly
    assert not [d for d in body["diagnostics"] if d["severity"] == "error"]


async def test_upgrade_unknown_node_is_404(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/flows", json={"spec": hello_spec("upg")})
    resp = await client.post("/api/v1/flows/upg/nodes/no-node/upgrade")
    assert resp.status_code == 404


# --------------------------------------------------------- publish / versions
async def test_publish_and_version_lifecycle(client: httpx.AsyncClient) -> None:
    created = (await client.post("/api/v1/flows", json={"spec": hello_spec("pub")})).json()
    flow_id = created["id"]

    assert (await client.get(f"/api/v1/flows/{flow_id}/versions")).json() == []

    published = await client.post(f"/api/v1/flows/{flow_id}/publish", json={"version": "minor"})
    assert published.status_code == 200
    body = published.json()
    assert body["published"] is True
    semver = body["version"]["semver"]

    versions = await client.get(f"/api/v1/flows/{flow_id}/versions")
    assert [v["semver"] for v in versions.json()] == [semver]

    one = await client.get(f"/api/v1/flows/{flow_id}/versions/{semver}")
    assert one.status_code == 200
    assert one.json()["flowspec"]["flow"]["slug"] == "pub"

    missing = await client.get(f"/api/v1/flows/{flow_id}/versions/99.99.99")
    assert missing.status_code == 404


async def test_publish_unrunnable_flow_reports_not_published(client: httpx.AsyncClient) -> None:
    created = (await client.post("/api/v1/flows", json={"spec": _unrunnable_spec()})).json()
    resp = await client.post(f"/api/v1/flows/{created['id']}/publish", json={"version": "minor"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["published"] is False
    assert any(d["severity"] == "error" for d in body["diagnostics"])


async def test_serve_version_pin_and_reset(client: httpx.AsyncClient) -> None:
    """SPEC §7.1 / SPEC.md:877 — the serve pin (latest_published | vX.Y.Z) is settable."""
    created = (await client.post("/api/v1/flows", json={"spec": hello_spec("pin")})).json()
    flow_id = created["id"]
    assert created["serve_version"] == "latest_published"
    await client.post(f"/api/v1/flows/{flow_id}/publish", json={"version": "minor"})  # 0.1.0
    await client.post(f"/api/v1/flows/{flow_id}/publish", json={"version": "minor"})  # 0.2.0

    pinned = await client.post(f"/api/v1/flows/{flow_id}/serve-version", json={"serve": "0.1.0"})
    assert pinned.status_code == 200
    assert pinned.json()["serve_version"] == "0.1.0"

    # SPEC spells the pin `vX.Y.Z` — the v prefix is accepted and normalized
    v_prefixed = await client.post(
        f"/api/v1/flows/{flow_id}/serve-version", json={"serve": "v0.2.0"}
    )
    assert v_prefixed.status_code == 200
    assert v_prefixed.json()["serve_version"] == "0.2.0"

    missing = await client.post(f"/api/v1/flows/{flow_id}/serve-version", json={"serve": "9.9.9"})
    assert missing.status_code == 404

    reset = await client.post(
        f"/api/v1/flows/{flow_id}/serve-version", json={"serve": "latest_published"}
    )
    assert reset.status_code == 200
    assert reset.json()["serve_version"] == "latest_published"


async def test_rollback_success_and_unknown_version(client: httpx.AsyncClient) -> None:
    created = (await client.post("/api/v1/flows", json={"spec": hello_spec("roll")})).json()
    flow_id = created["id"]
    published = await client.post(f"/api/v1/flows/{flow_id}/publish", json={"version": "minor"})
    semver = published.json()["version"]["semver"]

    rolled = await client.post(f"/api/v1/flows/{flow_id}/versions/{semver}/rollback")
    assert rolled.status_code == 200
    assert rolled.json()["id"] == flow_id

    missing = await client.post(f"/api/v1/flows/{flow_id}/versions/0.0.0/rollback")
    assert missing.status_code == 404


# ------------------------------------------------------------------- export
async def test_export_json_and_python(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/flows", json={"spec": hello_spec("exp")})

    as_json = await client.get("/api/v1/flows/exp/export")
    assert as_json.status_code == 200
    assert as_json.json()["flow"]["slug"] == "exp"

    as_py = await client.get("/api/v1/flows/exp/export", params={"format": "python"})
    assert as_py.status_code == 200
    assert as_py.headers["content-type"].startswith("text/plain")
    assert "StateGraph" in as_py.text or "def " in as_py.text  # emitted python source


async def test_import_creates_flow(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/flows/import", json={"spec": hello_spec("imported")})
    assert resp.status_code == 201
    assert resp.json()["slug"] == "imported"
    assert (await client.get("/api/v1/flows/imported")).status_code == 200


async def test_import_upsert_replaces_existing_slug(client: httpx.AsyncClient) -> None:
    first = hello_spec("dup")
    first["flow"]["description"] = "v1"
    assert (await client.post("/api/v1/flows/import", json={"spec": first})).status_code == 201
    second = hello_spec("dup")
    second["flow"]["description"] = "v2"
    resp = await client.post("/api/v1/flows/import", json={"spec": second})
    assert resp.status_code == 201
    assert resp.json()["description"] == "v2"  # upserted in place, not a new flow
    dup = [f for f in (await client.get("/api/v1/flows")).json() if f["slug"] == "dup"]
    assert len(dup) == 1


async def test_import_without_upsert_conflicts(client: httpx.AsyncClient) -> None:
    assert (
        await client.post("/api/v1/flows/import", json={"spec": hello_spec("noup")})
    ).status_code == 201
    resp = await client.post(
        "/api/v1/flows/import", json={"spec": hello_spec("noup"), "upsert": False}
    )
    assert resp.status_code == 409


async def test_import_multi_flow_array(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/flows/import",
        json={"specs": [hello_spec("multi-a"), hello_spec("multi-b")]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["count"] == 2
    assert {f["slug"] for f in body["imported"]} == {"multi-a", "multi-b"}


async def test_import_empty_is_422(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/flows/import", json={})
    assert resp.status_code == 422
