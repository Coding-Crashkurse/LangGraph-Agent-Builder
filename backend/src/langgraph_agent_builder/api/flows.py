"""Flows & versions API (SPEC §9.1)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from langgraph_agent_builder.api.deps import Services, StudioAuth
from langgraph_agent_builder.db.models import FlowRow, FlowVersionRow
from langgraph_agent_builder.schema.flowspec import FlowSpecError, parse_flowspec

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


class ImportBody(BaseModel):
    spec: dict[str, Any] | None = None  # single flow (back-compat)
    specs: list[dict[str, Any]] | None = None  # multi-flow array
    upsert: bool = True  # replace an existing flow with the same slug instead of 409


class PublishBody(BaseModel):
    version: str = Field(default="patch", description="major|minor|patch or explicit semver")
    changelog: str = ""


class LockBody(BaseModel):
    locked: bool = True


class ServeVersionBody(BaseModel):
    serve: str = Field(
        default="latest_published", description='"latest_published" or a published semver'
    )


@router.get("")
async def list_flows(
    svc: Services,
    tag: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    rows = await svc.flows.list(tag=tag, q=q, limit=limit, offset=offset)
    latest = await svc.flows.latest_versions([row.id for row in rows])
    return [flow_info(row, latest[row.id].semver if row.id in latest else None) for row in rows]


@router.post("", status_code=201)
async def create_flow(body: FlowCreate, svc: Services) -> dict[str, Any]:
    try:
        parsed = parse_flowspec(body.spec)
    except FlowSpecError as exc:
        raise HTTPException(422, f"invalid FlowSpec: {exc}") from exc
    # slug uniqueness is enforced in FlowService (SlugConflictError → 409)
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
    try:
        parsed = parse_flowspec(body.spec)
    except FlowSpecError as exc:
        raise HTTPException(422, f"invalid FlowSpec: {exc}") from exc
    # lock + slug rules live in FlowService (FlowLockedError/SlugConflictError → 409)
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
    if updated is None:  # deleted between resolve and update
        raise HTTPException(404, "flow not found")
    return flow_info(updated)


@router.post("/{id_or_slug}/serve-version")
async def set_serve_version(
    id_or_slug: str, body: ServeVersionBody, svc: Services
) -> dict[str, Any]:
    """Pin the published version an agent serves (SPEC §7.1: latest_published | vX.Y.Z)."""
    row = await _resolve(svc, id_or_slug)
    serve = body.serve
    if serve != "latest_published":
        serve = serve.removeprefix("v")
        if await svc.flows.get_version(row.id, serve) is None:
            raise HTTPException(404, "version not found")
    await svc.flows.set_serve_version(row.id, serve)
    await svc.remount()
    updated = await _resolve(svc, id_or_slug)
    latest = await svc.flows.latest_version(updated.id)
    return flow_info(updated, latest.semver if latest else None)


@router.post("/{id_or_slug}/nodes/{node_id}/upgrade")
async def upgrade_node(id_or_slug: str, node_id: str, svc: Services) -> dict[str, Any]:
    row = await _resolve(svc, id_or_slug)
    if row.locked:
        raise HTTPException(409, "flow is locked")
    updated, error = await svc.flows.upgrade_node(row.id, node_id, svc.registry)
    if updated is None:
        # a missing component is an install problem, not a missing resource
        status = 422 if error == "component not installed" else 404
        raise HTTPException(status, error or "upgrade failed")
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

        from langgraph_agent_builder.compiler.export_python import export_python

        return PlainTextResponse(export_python(parse_flowspec(row.spec), svc.registry))
    return row.spec


@router.post("/import", status_code=201)
async def import_flow(body: ImportBody, svc: Services) -> Any:
    """Import one or many flows (SPEC §9.1).

    ``{"spec": …}`` imports a single flow (returns the flow object, back-compat).
    ``{"specs": [ … ]}`` imports many (returns ``{"imported": [...], "count": n}``).
    With ``upsert`` (default), a spec whose slug already exists updates that flow
    in place instead of a 409; a locked target is refused with 409.
    """
    raw = body.specs if body.specs is not None else ([body.spec] if body.spec is not None else [])
    if not raw:
        raise HTTPException(422, "provide `spec` or `specs`")
    results: list[dict[str, Any]] = []
    for one in raw:
        try:
            parsed = parse_flowspec(one)
        except FlowSpecError as exc:
            raise HTTPException(422, f"invalid FlowSpec: {exc}") from exc
        existing = await svc.flows.get_by_slug(parsed.flow.slug)
        if existing is not None:
            if not body.upsert:
                raise HTTPException(409, f"slug {parsed.flow.slug!r} already exists")
            # locked target → FlowLockedError → 409 via the exception-handler layer
            row = await svc.flows.update(existing.id, parsed)
            if row is None:  # pragma: no cover - lost between fetch and update
                raise HTTPException(404, "flow not found")
        else:
            row = await svc.flows.create(parsed)
        results.append(flow_info(row))
    if body.specs is None:  # single-spec form → return the flow object directly
        return results[0]
    return {"imported": results, "count": len(results)}
