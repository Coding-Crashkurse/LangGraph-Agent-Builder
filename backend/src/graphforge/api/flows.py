"""Flow CRUD, validation and publish/unpublish (CLAUDE.md §13)."""

import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from graphforge.api.deps import ManagerDep, RegistryDep, SessionmakerDep, SettingsDep
from graphforge.compiler.build import FlowValidationError, validate
from graphforge.compiler.spec import (
    AgentCardSpec,
    EdgeSpec,
    FlowSpec,
    MCPToolSpec,
    NodeSpec,
    PublishSpec,
    ValidationIssue,
)
from graphforge.db.models import Flow

router = APIRouter(prefix="/api/flows", tags=["flows"])


# -- wire models --------------------------------------------------------------


class FlowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = None
    description: str = ""


class FlowSave(BaseModel):
    name: str | None = None
    description: str | None = None
    nodes: list[NodeSpec] | None = None
    edges: list[EdgeSpec] | None = None


class PublishRequest(BaseModel):
    a2a: bool = True
    mcp: bool = False
    agent_card: AgentCardSpec = Field(default_factory=AgentCardSpec)
    mcp_tool: MCPToolSpec = Field(default_factory=MCPToolSpec)


class ValidateRequest(BaseModel):
    nodes: list[NodeSpec] | None = None
    edges: list[EdgeSpec] | None = None


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64]
    return slug or f"flow-{uuid.uuid4().hex[:8]}"


def spec_from_row(row: Flow) -> FlowSpec:
    graph = row.graph or {}
    return FlowSpec(
        id=str(row.id),
        slug=row.slug,
        name=row.name,
        description=row.description or "",
        version=row.version,
        nodes=[NodeSpec(**n) for n in graph.get("nodes", [])],
        edges=[EdgeSpec(**e) for e in graph.get("edges", [])],
        publish=PublishSpec(
            a2a=row.publish_a2a,
            mcp=row.publish_mcp,
            agent_card=AgentCardSpec(**(row.agent_card or {})),
            mcp_tool=MCPToolSpec(**(row.mcp_tool or {})),
        ),
    )


def flow_out(row: Flow, manager: Any) -> dict[str, Any]:
    spec = spec_from_row(row)
    return {
        **spec.model_dump(),
        "is_published": row.is_published,
        "endpoints": manager.endpoints(str(row.id)),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _get_row(sessionmaker: Any, flow_id: str) -> Flow:
    try:
        key = uuid.UUID(flow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="flow not found") from exc
    async with sessionmaker() as session:
        row = await session.get(Flow, key)
    if row is None:
        raise HTTPException(status_code=404, detail="flow not found")
    return row


# -- routes -------------------------------------------------------------------


@router.get("")
async def list_flows(sessionmaker: SessionmakerDep, manager: ManagerDep) -> list[dict[str, Any]]:
    async with sessionmaker() as session:
        rows = (await session.execute(select(Flow).order_by(Flow.updated_at.desc()))).scalars()
        return [flow_out(row, manager) for row in rows]


@router.post("", status_code=201)
async def create_flow(
    body: FlowCreate, sessionmaker: SessionmakerDep, manager: ManagerDep
) -> dict[str, Any]:
    slug = body.slug or _slugify(body.name)
    async with sessionmaker() as session:
        exists = (
            await session.execute(select(Flow.id).where(Flow.slug == slug))
        ).scalar_one_or_none()
        if exists is not None:
            slug = f"{slug[:55]}-{uuid.uuid4().hex[:6]}"
        row = Flow(
            slug=slug,
            name=body.name,
            description=body.description,
            graph={"nodes": [], "edges": []},
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return flow_out(row, manager)


@router.get("/{flow_id}")
async def get_flow(
    flow_id: str, sessionmaker: SessionmakerDep, manager: ManagerDep
) -> dict[str, Any]:
    row = await _get_row(sessionmaker, flow_id)
    return flow_out(row, manager)


@router.put("/{flow_id}")
async def save_flow(
    flow_id: str,
    body: FlowSave,
    sessionmaker: SessionmakerDep,
    manager: ManagerDep,
    registry: RegistryDep,
) -> dict[str, Any]:
    async with sessionmaker() as session:
        row = await session.get(Flow, uuid.UUID(flow_id))
        if row is None:
            raise HTTPException(status_code=404, detail="flow not found")
        if body.name is not None:
            row.name = body.name
        if body.description is not None:
            row.description = body.description
        if body.nodes is not None or body.edges is not None:
            graph = dict(row.graph or {"nodes": [], "edges": []})
            if body.nodes is not None:
                graph["nodes"] = [n.model_dump() for n in body.nodes]
            if body.edges is not None:
                graph["edges"] = [e.model_dump() for e in body.edges]
            row.graph = graph
        row.version += 1
        await session.commit()
        await session.refresh(row)

    issues: list[ValidationIssue] = []
    if row.is_published:  # republish on save (CLAUDE.md §13)
        spec = spec_from_row(row)
        try:
            await manager.publish_flow(spec)
        except FlowValidationError as exc:
            issues = exc.issues
            await manager.unpublish_flow(str(row.id))
            async with sessionmaker() as session:
                fresh = await session.get(Flow, row.id)
                if fresh is not None:
                    fresh.is_published = False
                    await session.commit()
                    row = fresh

    return {**flow_out(row, manager), "issues": [i.model_dump() for i in issues]}


@router.delete("/{flow_id}", status_code=204)
async def delete_flow(flow_id: str, sessionmaker: SessionmakerDep, manager: ManagerDep) -> None:
    row = await _get_row(sessionmaker, flow_id)
    await manager.unpublish_flow(str(row.id))
    async with sessionmaker() as session:
        fresh = await session.get(Flow, row.id)
        if fresh is not None:
            await session.delete(fresh)
            await session.commit()


@router.post("/{flow_id}/validate")
async def validate_flow(
    flow_id: str,
    body: ValidateRequest | None,
    sessionmaker: SessionmakerDep,
    registry: RegistryDep,
) -> dict[str, Any]:
    row = await _get_row(sessionmaker, flow_id)
    spec = spec_from_row(row)
    if body is not None:
        if body.nodes is not None:
            spec.nodes = body.nodes
        if body.edges is not None:
            spec.edges = body.edges
    issues = validate(spec, registry)
    return {
        "valid": not any(i.severity == "error" for i in issues),
        "issues": [i.model_dump() for i in issues],
    }


@router.post("/{flow_id}/publish")
async def publish_flow(
    flow_id: str,
    body: PublishRequest,
    sessionmaker: SessionmakerDep,
    manager: ManagerDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    if not body.a2a and not body.mcp:
        raise HTTPException(status_code=422, detail="enable at least one of a2a/mcp")
    async with sessionmaker() as session:
        row = await session.get(Flow, uuid.UUID(flow_id))
        if row is None:
            raise HTTPException(status_code=404, detail="flow not found")
        row.publish_a2a = body.a2a
        row.publish_mcp = body.mcp
        row.agent_card = body.agent_card.model_dump()
        row.mcp_tool = body.mcp_tool.model_dump()
        row.is_published = True
        await session.commit()
        await session.refresh(row)

    spec = spec_from_row(row)
    try:
        await manager.publish_flow(spec)
    except FlowValidationError as exc:
        async with sessionmaker() as session:
            fresh = await session.get(Flow, row.id)
            if fresh is not None:
                fresh.is_published = False
                await session.commit()
        return {
            "published": False,
            "issues": [i.model_dump() for i in exc.issues],
        }
    mounted = manager.mounted(str(row.id))
    return {
        "published": True,
        "issues": [],
        "endpoints": manager.endpoints(str(row.id)),
        "agent_card": (
            mounted.card.model_dump(exclude_none=True, by_alias=True)
            if mounted and mounted.card
            else None
        ),
    }


@router.post("/{flow_id}/unpublish")
async def unpublish_flow(
    flow_id: str, sessionmaker: SessionmakerDep, manager: ManagerDep
) -> dict[str, Any]:
    row = await _get_row(sessionmaker, flow_id)
    await manager.unpublish_flow(str(row.id))
    async with sessionmaker() as session:
        fresh = await session.get(Flow, row.id)
        if fresh is not None:
            fresh.is_published = False
            await session.commit()
    return {"published": False}
