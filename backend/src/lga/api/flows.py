"""Flows & versions API (SPEC §9.1)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from lga.api.deps import Services, StudioAuth
from lga.db.models import FlowRow, FlowVersionRow
from lga.schema.flowspec import FlowSpecError, parse_flowspec

router = APIRouter(prefix="/flows", tags=["flows"], dependencies=[StudioAuth])


def flow_info(row: FlowRow, published: str | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "slug": row.slug,
        "name": row.name,
        "description": row.description,
        "spec": row.spec,
        "locked": bool(getattr(row, "locked", False)),
        "serve_version": row.serve_version,
        "published_version": published,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def version_info(row: FlowVersionRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "flow_id": row.flow_id,
        "semver": row.semver,
        "changelog": row.changelog,
        "published_at": row.published_at.isoformat(),
    }


class FlowCreate(BaseModel):
    spec: dict[str, Any]


class FlowPatch(BaseModel):
    spec: dict[str, Any]


class PublishBody(BaseModel):
    version: str = Field(default="patch", description="major|minor|patch or explicit semver")
    changelog: str = ""


class LockBody(BaseModel):
    locked: bool = True


def _matches(row: FlowRow, tag: str | None, q: str | None) -> bool:
    if tag:
        tags = ((row.spec or {}).get("flow") or {}).get("tags") or []
        if tag not in tags:
            return False
    if q:
        needle = q.lower()
        if needle not in (row.name or "").lower() and needle not in (row.slug or "").lower():
            return False
    return True


@router.get("")
async def list_flows(
    svc: Services,
    tag: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    result = []
    for row in await svc.flows.list():
        if not _matches(row, tag, q):
            continue
        latest = await svc.flows.latest_version(row.id)
        result.append(flow_info(row, latest.semver if latest else None))
    return result


@router.post("", status_code=201)
async def create_flow(body: FlowCreate, svc: Services) -> dict[str, Any]:
    try:
        parsed = parse_flowspec(body.spec)
    except FlowSpecError as exc:
        raise HTTPException(422, f"invalid FlowSpec: {exc}") from exc
    if await svc.flows.get_by_slug(parsed.flow.slug) is not None:
        raise HTTPException(409, f"slug {parsed.flow.slug!r} already exists")
    row = await svc.flows.create(parsed)
    return flow_info(row)


async def _resolve(svc: Services, id_or_slug: str) -> FlowRow:
    row: FlowRow | None = await svc.flows.resolve(id_or_slug)
    if row is None:
        raise HTTPException(404, "flow not found")
    return row


@router.get("/{id_or_slug}")
async def get_flow(id_or_slug: str, svc: Services) -> dict[str, Any]:
    row = await _resolve(svc, id_or_slug)
    latest = await svc.flows.latest_version(row.id)
    return flow_info(row, latest.semver if latest else None)


@router.patch("/{id_or_slug}")
async def update_flow(id_or_slug: str, body: FlowPatch, svc: Services) -> dict[str, Any]:
    current = await _resolve(svc, id_or_slug)
    if current.locked:
        raise HTTPException(409, "flow is locked; unlock it before editing")
    try:
        parsed = parse_flowspec(body.spec)
    except FlowSpecError as exc:
        raise HTTPException(422, f"invalid FlowSpec: {exc}") from exc
    other = await svc.flows.get_by_slug(parsed.flow.slug)
    if other is not None and other.id != current.id:
        raise HTTPException(409, f"slug {parsed.flow.slug!r} already exists")
    row = await svc.flows.update(current.id, parsed)
    if row is None:
        raise HTTPException(404, "flow not found")
    return flow_info(row)


@router.delete("/{id_or_slug}", status_code=204)
async def delete_flow(id_or_slug: str, svc: Services) -> None:
    row = await _resolve(svc, id_or_slug)
    if not await svc.flows.delete(row.id):
        raise HTTPException(404, "flow not found")
    await svc.remount()


@router.post("/{id_or_slug}/lock")
async def lock_flow(id_or_slug: str, body: LockBody, svc: Services) -> dict[str, Any]:
    row = await _resolve(svc, id_or_slug)
    updated = await svc.flows.set_locked(row.id, body.locked)
    assert updated is not None
    return flow_info(updated)


@router.post("/{id_or_slug}/nodes/{node_id}/upgrade")
async def upgrade_node(id_or_slug: str, node_id: str, svc: Services) -> dict[str, Any]:
    row = await _resolve(svc, id_or_slug)
    if row.locked:
        raise HTTPException(409, "flow is locked")
    updated, error = await svc.flows.upgrade_node(row.id, node_id, svc.registry)
    if updated is None:
        raise HTTPException(404, error or "upgrade failed")
    diags, _compiled = await svc.orchestrator.validate(updated.spec)
    return {
        "flow": flow_info(updated),
        "diagnostics": [d.model_dump(mode="json") for d in diags],
    }


@router.post("/{id_or_slug}/validate")
async def validate_flow(
    id_or_slug: str, svc: Services, deep: bool = Query(default=False)
) -> dict[str, Any]:
    row = await _resolve(svc, id_or_slug)
    diags, compiled = await svc.orchestrator.validate(row.spec, deep=deep)
    return {
        "diagnostics": [d.model_dump(mode="json") for d in diags],
        "compile_report": compiled.report.model_dump(mode="json") if compiled else None,
    }


@router.post("/{id_or_slug}/publish")
async def publish_flow(id_or_slug: str, body: PublishBody, svc: Services) -> dict[str, Any]:
    row = await _resolve(svc, id_or_slug)
    diags, _compiled = await svc.orchestrator.validate(row.spec)
    version, all_diags = await svc.flows.publish(
        row.id,
        registry=svc.registry,
        bump=body.version,
        changelog=body.changelog,
        compile_diagnostics=diags,
    )
    if version is None:
        return {
            "published": False,
            "diagnostics": [d.model_dump(mode="json") for d in all_diags],
        }
    await svc.remount()
    return {
        "published": True,
        "version": version_info(version),
        "diagnostics": [d.model_dump(mode="json") for d in all_diags],
    }


@router.get("/{id_or_slug}/versions")
async def list_versions(id_or_slug: str, svc: Services) -> list[dict[str, Any]]:
    row = await _resolve(svc, id_or_slug)
    return [version_info(v) for v in await svc.flows.versions(row.id)]


@router.get("/{id_or_slug}/versions/{semver}")
async def get_version(id_or_slug: str, semver: str, svc: Services) -> dict[str, Any]:
    row = await _resolve(svc, id_or_slug)
    version = await svc.flows.get_version(row.id, semver)
    if version is None:
        raise HTTPException(404, "version not found")
    return {**version_info(version), "flowspec": version.flowspec}


@router.post("/{id_or_slug}/versions/{semver}/rollback")
async def rollback(id_or_slug: str, semver: str, svc: Services) -> dict[str, Any]:
    current = await _resolve(svc, id_or_slug)
    row = await svc.flows.rollback(current.id, semver)
    if row is None:
        raise HTTPException(404, "version not found")
    return flow_info(row)


@router.get("/{id_or_slug}/export")
async def export_flow(id_or_slug: str, svc: Services, format: str = Query(default="json")) -> Any:
    row = await _resolve(svc, id_or_slug)
    if format == "python":
        from fastapi.responses import PlainTextResponse

        from lga.compiler.export_python import export_python

        return PlainTextResponse(export_python(parse_flowspec(row.spec), svc.registry))
    return row.spec


@router.post("/import", status_code=201)
async def import_flow(body: FlowCreate, svc: Services) -> dict[str, Any]:
    return await create_flow(body, svc)
