"""Secrets, API keys, files, MCP servers, misc endpoints (SPEC §9.6–§9.8, §11.7)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from langgraph_agent_builder.api.deps import Services, StudioAuth

router = APIRouter(tags=["settings"], dependencies=[StudioAuth])


# ---------------------------------------------------------------- global variables (§10.3)
class VariableBody(BaseModel):
    name: str
    value: str
    kind: str = Field(default="generic", pattern="^(generic|credential)$")


@router.get("/variables")
async def list_variables(
    svc: Services,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    from langgraph_agent_builder.services.secrets import variable_usage

    variables: list[dict[str, Any]] = await svc.secrets.list(limit=limit, offset=offset)
    usage = variable_usage(await svc.flows.list())
    for variable in variables:
        variable["in_use_by"] = usage.get(variable["name"], [])
    return variables


@router.post("/variables", status_code=201)
async def set_variable(body: VariableBody, svc: Services) -> dict[str, Any]:
    await svc.secrets.set(body.name, body.value, body.kind)
    return {"name": body.name, "kind": body.kind}


@router.delete("/variables/{name}", status_code=204)
async def delete_variable(name: str, svc: Services) -> None:
    if not await svc.secrets.delete(name):
        raise HTTPException(404, "variable not found")


# ---------------------------------------------------------------- api keys (§10.4)
class ApiKeyBody(BaseModel):
    name: str = ""
    scopes: list[str]


@router.get("/apikeys")
async def list_apikeys(
    svc: Services,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    keys: list[dict[str, Any]] = await svc.apikeys.list(limit=limit, offset=offset)
    return keys


@router.post("/apikeys", status_code=201)
async def create_apikey(body: ApiKeyBody, svc: Services) -> dict[str, Any]:
    try:
        key, info = await svc.apikeys.create(body.scopes, body.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**info, "key": key}  # plaintext returned exactly once


@router.delete("/apikeys/{key_id}", status_code=204)
async def revoke_apikey(key_id: str, svc: Services) -> None:
    if not await svc.apikeys.revoke(key_id):
        raise HTTPException(404, "api key not found")


# ---------------------------------------------------------------- files (§9.6)
@router.post("/files", status_code=201)
async def upload_file(file: UploadFile, svc: Services) -> dict[str, Any]:
    from langgraph_agent_builder.services.files import CHUNK_SIZE, FileTooLargeError

    async def chunks() -> AsyncIterator[bytes]:
        while True:
            block = await file.read(CHUNK_SIZE)
            if not block:
                return
            yield block

    try:
        saved: dict[str, Any] = await svc.files.save_stream(
            file.filename or "upload",
            file.content_type or "application/octet-stream",
            chunks(),
            size_hint=file.size,  # Content-Length → reject oversize before reading
        )
        return saved
    except FileTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc


@router.get("/files")
async def list_files(
    svc: Services,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = await svc.files.list(limit=limit, offset=offset)
    return files


# ---------------------------------------------------------------- mcp servers (§8.3, §11.7)
class McpServerBody(BaseModel):
    name: str
    transport: str = Field(default="streamable_http", pattern="^(stdio|streamable_http|sse)$")
    config: dict[str, Any] = Field(default_factory=dict)


@router.get("/mcp-servers")
async def list_mcp_servers(svc: Services) -> list[dict[str, Any]]:
    servers: list[dict[str, Any]] = await svc.mcp_servers.list()
    return servers


@router.post("/mcp-servers", status_code=201)
async def upsert_mcp_server(body: McpServerBody, svc: Services) -> dict[str, Any]:
    server: dict[str, Any] = await svc.mcp_servers.upsert(body.name, body.transport, body.config)
    return server


@router.delete("/mcp-servers/{name}", status_code=204)
async def delete_mcp_server(name: str, svc: Services) -> None:
    if not await svc.mcp_servers.delete(name):
        raise HTTPException(404, "mcp server not found")


@router.get("/mcp/config")
async def mcp_client_config(svc: Services) -> dict[str, Any]:
    """Ready-to-paste client JSON (SPEC §8.1)."""
    return {
        "mcpServers": {
            "langgraph-agent-builder": {
                "type": "http",
                "url": f"{svc.settings.host_url}/mcp",
                **(
                    {"headers": {"X-API-Key": "<your lab_sk_… key with mcp:invoke scope>"}}
                    if svc.settings.auth_enabled
                    else {}
                ),
            }
        }
    }


# ---------------------------------------------------------------- health (§9.8)
# own router: mounted under /api/v1 AND unprefixed for load balancers — /version
# and /config must NOT ride along at the root
health_router = APIRouter(tags=["misc"])


@health_router.get("/health")
async def health(svc: Services) -> dict[str, Any]:
    """db + checkpointer + vector store connections (SPEC §9.8)."""
    db_ok = True
    checkpointer_ok = True
    try:
        from sqlalchemy import text

        async with svc.sessions() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    try:
        await svc.checkpointers.get()
    except Exception:
        checkpointer_ok = False
    vectorstores = {
        conn["name"]: bool(conn["ok"]) for conn in await svc.vectorstores.list_with_health()
    }
    status = "ok" if db_ok and checkpointer_ok and all(vectorstores.values()) else "degraded"
    from langgraph_agent_builder.vectorstores import installed_backends

    return {
        "status": status,
        "db": db_ok,
        "checkpointer": checkpointer_ok,
        "vectorstores": vectorstores,
        "tier": svc.settings.storage_tier,
        "vector_backends": installed_backends(),
    }


# ---------------------------------------------------------------- misc (§9.8)
misc_router = APIRouter(tags=["misc"])


@misc_router.get("/version")
async def version(svc: Services) -> dict[str, Any]:
    import langgraph

    import langgraph_agent_builder as lab_pkg

    try:
        from a2a.utils.constants import DEFAULT_PROTOCOL_VERSION  # type: ignore

        protocol = DEFAULT_PROTOCOL_VERSION
    except Exception:
        protocol = "0.3.x"
    from langgraph_agent_builder.vectorstores import installed_backends

    return {
        "langgraph-agent-builder": lab_pkg.__version__,
        "a2a_protocol": protocol,
        "langgraph": getattr(langgraph, "__version__", "unknown"),
        "db_backend": svc.settings.storage_tier,
        "vector_backends": installed_backends(),
    }


@misc_router.get("/config", dependencies=[StudioAuth])
async def config(svc: Services) -> dict[str, Any]:
    """Studio-relevant settings only — an explicit allowlist, so new sensitive
    settings (DSNs, key material) stay private by default (SPEC §10.5)."""
    s = svc.settings
    return {
        "env": s.env,
        "host_url": s.host_url,
        "auth_enabled": s.auth_enabled,
        "storage_tier": s.storage_tier,
        "auto_saving": s.auto_saving,
        "auto_saving_interval_ms": s.auto_saving_interval_ms,
        "max_file_size_mb": s.max_file_size_mb,
        "max_text_length": s.max_text_length,
        "webhook_auth": s.webhook_auth,
        "cancel_on_disconnect": s.cancel_on_disconnect,
        "checkpoint_ttl_days": s.checkpoint_ttl_days,
        "recursion_limit_default": s.recursion_limit_default,
        "create_starter_flows": s.create_starter_flows,
        "fallback_to_env_var": s.fallback_to_env_var,
        "secret_key": "***" if s.secret_key else "",  # masked, kept for back-compat
    }


# files need token-only access (A2A FileParts) — outside StudioAuth
public_files_router = APIRouter(tags=["files"])


@public_files_router.get("/files/{file_id}")
async def download_file(
    file_id: str, svc: Services, token: str = Query(default="")
) -> FileResponse:
    # the per-file token is REQUIRED here: an absent/empty token must never
    # bypass the gate (SPEC §9.6 — presigned-ish tokened URL)
    row = await svc.files.get_public(file_id, token)
    if row is None:
        raise HTTPException(404, "file not found")
    return FileResponse(  # streams from disk — no full read into memory
        row.path,
        media_type=row.mime,
        filename=row.name,
        content_disposition_type="inline",
    )
