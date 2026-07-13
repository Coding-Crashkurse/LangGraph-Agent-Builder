"""Flows API: drafts, validation, publish, playground, import/export (SPEC §3, §5).

The request/response definition payload IS the canonical FlowDefinition JSON
object (canvas positions confined to ``layout``). Validation issues carry a
``source`` marker so local (advisory) and runtime (authoritative) results
render identically in the frontend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from agentplane_core import ValidationIssue, validate_structure
from fastapi import APIRouter, Body, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from langgraph_agent_builder.api.deps import CurrentPrincipal, Services
from langgraph_agent_builder.serialization import (
    dump_definition_yaml,
    loads_definition_data,
    parse_definition,
)
from langgraph_agent_builder.services.flows import StoredFlow

router = APIRouter(prefix="/flows", tags=["flows"])

IssueSource = Literal["local", "runtime"]

DefinitionBody = Annotated[dict[str, Any], Body()]


class SourcedIssue(BaseModel):
    """A ValidationIssue plus where it came from — both render identically."""

    model_config = ConfigDict(frozen=True)

    code: str
    severity: Literal["error", "warning"]
    path: str
    message: str
    source: IssueSource

    @classmethod
    def wrap(cls, issue: ValidationIssue, source: IssueSource) -> SourcedIssue:
        return cls(
            code=issue.code,
            severity=issue.severity,
            path=issue.path,
            message=issue.message,
            source=source,
        )


class ValidationResponse(BaseModel):
    valid: bool
    runtime_checked: bool
    issues: list[SourcedIssue]


class FlowSummary(BaseModel):
    name: str
    display_name: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    expose_kind: str = "a2a"
    updated_at: datetime


class FlowDetail(BaseModel):
    name: str
    definition: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PublishResponse(BaseModel):
    name: str
    version: int
    endpoint_url: str
    registry_id: str | None = None


class PlaygroundResponse(BaseModel):
    name: str
    endpoint_url: str


class ImportResponse(BaseModel):
    name: str
    created: bool


def _summary(flow: StoredFlow) -> FlowSummary:
    defn = flow.definition
    expose = defn.get("expose")
    expose_kind = expose.get("kind", "a2a") if isinstance(expose, dict) else "a2a"
    return FlowSummary(
        name=flow.name,
        display_name=str(defn.get("display_name", "") or ""),
        description=str(defn.get("description", "") or ""),
        tags=[t for t in defn.get("tags", []) if isinstance(t, str)],
        expose_kind=str(expose_kind),
        updated_at=flow.updated_at,
    )


def _detail(flow: StoredFlow) -> FlowDetail:
    return FlowDetail(
        name=flow.name,
        definition=flow.definition,
        created_at=flow.created_at,
        updated_at=flow.updated_at,
    )


@router.get("")
async def list_flows(svc: Services, principal: CurrentPrincipal) -> list[FlowSummary]:
    return [_summary(flow) for flow in await svc.store.list(principal.sub)]


@router.post("", status_code=201)
async def create_flow(
    definition: DefinitionBody, svc: Services, principal: CurrentPrincipal
) -> FlowDetail:
    return _detail(await svc.store.create(definition, principal.sub))


@router.post("/validate")
async def validate_flow(
    definition: DefinitionBody,
    svc: Services,
    principal: CurrentPrincipal,
    runtime: Annotated[bool, Query()] = True,
) -> ValidationResponse:
    """Merged local (advisory) + runtime (authoritative) validation.

    ``runtime=false`` runs the instant local check only — used by the
    canvas's silent re-validate while editing; the Validate button asks the
    runtime for the full picture.
    """
    local = validate_structure(definition)
    issues = [SourcedIssue.wrap(i, "local") for i in local]
    runtime_result = await svc.gateway.validate(definition, principal.token) if runtime else None
    if runtime_result is not None:
        seen = {(i.code, i.path) for i in local}
        issues += [
            SourcedIssue.wrap(i, "runtime")
            for i in runtime_result.issues
            if (i.code, i.path) not in seen
        ]
    valid = not any(i.severity == "error" for i in issues)
    return ValidationResponse(
        valid=valid, runtime_checked=runtime_result is not None, issues=issues
    )


@router.get("/{name}")
async def get_flow(name: str, svc: Services, principal: CurrentPrincipal) -> FlowDetail:
    return _detail(await svc.store.get(name, principal.sub))


@router.put("/{name}")
async def save_flow(
    name: str, definition: DefinitionBody, svc: Services, principal: CurrentPrincipal
) -> FlowDetail:
    """Save the builder-local draft (with layout); no platform interaction."""
    return _detail(await svc.store.save(name, definition, principal.sub))


@router.delete("/{name}", status_code=204)
async def delete_flow(name: str, svc: Services, principal: CurrentPrincipal) -> None:
    await svc.store.delete(name, principal.sub)


@router.post("/{name}/publish")
async def publish_flow(name: str, svc: Services, principal: CurrentPrincipal) -> PublishResponse:
    """Update the runtime draft + deploy; registration happens platform-side."""
    stored = await svc.store.get(name, principal.sub)
    defn = parse_definition(stored.definition)
    deployment = await svc.gateway.publish(defn, principal.token)
    return PublishResponse(
        name=deployment.name,
        version=deployment.version,
        endpoint_url=deployment.endpoint_url,
        registry_id=str(deployment.registry_id) if deployment.registry_id else None,
    )


@router.post("/{name}/playground")
async def playground_flow(
    name: str, svc: Services, principal: CurrentPrincipal
) -> PlaygroundResponse:
    """Ephemeral deploy of the current draft; the chat panel talks A2A to it."""
    stored = await svc.store.get(name, principal.sub)
    defn = parse_definition(stored.definition)
    deployment = await svc.gateway.playground(defn, principal.token)
    return PlaygroundResponse(name=deployment.name, endpoint_url=deployment.endpoint_url)


@router.get("/{name}/export")
async def export_flow(
    name: str,
    svc: Services,
    principal: CurrentPrincipal,
    format: Annotated[Literal["yaml", "json"], Query()] = "yaml",
) -> Response:
    """Canonical FlowDefinition YAML/JSON — importable here, deployable via CLI."""
    stored = await svc.store.get(name, principal.sub)
    if format == "json":
        import json

        from langgraph_agent_builder.serialization import canonical_definition_dict

        payload = json.dumps(canonical_definition_dict(stored.definition), indent=2) + "\n"
        media, filename = "application/json", f"{name}.flow.json"
    else:
        payload = dump_definition_yaml(stored.definition)
        media, filename = "application/yaml", f"{name}.flow.yaml"
    return Response(
        content=payload,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", status_code=201)
async def import_flow(
    svc: Services,
    principal: CurrentPrincipal,
    body: Annotated[str, Body(media_type="application/yaml")],
    overwrite: Annotated[bool, Query()] = False,
) -> ImportResponse:
    """Import canonical FlowDefinition YAML/JSON; round-trip safe."""
    raw = loads_definition_data(body)
    if overwrite:
        stored, created = await svc.store.upsert(raw, principal.sub)
    else:
        stored, created = await svc.store.create(raw, principal.sub), True
    return ImportResponse(name=stored.name, created=created)
