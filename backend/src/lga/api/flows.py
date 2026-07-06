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


@router.get("")
async def list_flows(svc: Services) -> list[dict[str, Any]]:
    result = []
    for row in await svc.flows.list():
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


@router.get("/{flow_id}")
async def get_flow(flow_id: str, svc: Services) -> dict[str, Any]:
    row = await svc.flows.get(flow_id)
    if row is None:
        raise HTTPException(404, "flow not found")
    latest = await svc.flows.latest_version(row.id)
    return flow_info(row, latest.semver if latest else None)


@router.patch("/{flow_id}")
async def update_flow(flow_id: str, body: FlowPatch, svc: Services) -> dict[str, Any]:
    try:
        parsed = parse_flowspec(body.spec)
    except FlowSpecError as exc:
        raise HTTPException(422, f"invalid FlowSpec: {exc}") from exc
    other = await svc.flows.get_by_slug(parsed.flow.slug)
    if other is not None and other.id != flow_id:
        raise HTTPException(409, f"slug {parsed.flow.slug!r} already exists")
    row = await svc.flows.update(flow_id, parsed)
    if row is None:
        raise HTTPException(404, "flow not found")
    return flow_info(row)


@router.delete("/{flow_id}", status_code=204)
async def delete_flow(flow_id: str, svc: Services) -> None:
    if not await svc.flows.delete(flow_id):
        raise HTTPException(404, "flow not found")
    await svc.remount()


@router.post("/{flow_id}/validate")
async def validate_flow(
    flow_id: str, svc: Services, deep: bool = Query(default=False)
) -> dict[str, Any]:
    row = await svc.flows.get(flow_id)
    if row is None:
        raise HTTPException(404, "flow not found")
    diags, compiled = await svc.orchestrator.validate(row.spec, deep=deep)
    return {
        "diagnostics": [d.model_dump(mode="json") for d in diags],
        "compile_report": compiled.report.model_dump(mode="json") if compiled else None,
    }


@router.post("/{flow_id}/publish")
async def publish_flow(flow_id: str, body: PublishBody, svc: Services) -> dict[str, Any]:
    row = await svc.flows.get(flow_id)
    if row is None:
        raise HTTPException(404, "flow not found")
    diags, _compiled = await svc.orchestrator.validate(row.spec)
    version, all_diags = await svc.flows.publish(
        flow_id,
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


@router.get("/{flow_id}/versions")
async def list_versions(flow_id: str, svc: Services) -> list[dict[str, Any]]:
    return [version_info(v) for v in await svc.flows.versions(flow_id)]


@router.get("/{flow_id}/versions/{semver}")
async def get_version(flow_id: str, semver: str, svc: Services) -> dict[str, Any]:
    version = await svc.flows.get_version(flow_id, semver)
    if version is None:
        raise HTTPException(404, "version not found")
    return {**version_info(version), "flowspec": version.flowspec}


@router.post("/{flow_id}/versions/{semver}/rollback")
async def rollback(flow_id: str, semver: str, svc: Services) -> dict[str, Any]:
    row = await svc.flows.rollback(flow_id, semver)
    if row is None:
        raise HTTPException(404, "version not found")
    return flow_info(row)


@router.get("/{flow_id}/export")
async def export_flow(flow_id: str, svc: Services, format: str = Query(default="json")) -> Any:
    row = await svc.flows.get(flow_id)
    if row is None:
        raise HTTPException(404, "flow not found")
    if format == "python":
        from fastapi.responses import PlainTextResponse

        from lga.compiler.export_python import export_python

        return PlainTextResponse(export_python(parse_flowspec(row.spec), svc.registry))
    return row.spec


@router.post("/import", status_code=201)
async def import_flow(body: FlowCreate, svc: Services) -> dict[str, Any]:
    return await create_flow(body, svc)
