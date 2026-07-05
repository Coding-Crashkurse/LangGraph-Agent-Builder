"""Secrets, API keys, files, MCP servers, misc endpoints (SPEC §9.6–§9.8, §11.7)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lga.api.deps import Services, StudioAuth

router = APIRouter(tags=["settings"], dependencies=[StudioAuth])


# ---------------------------------------------------------------- global variables (§10.3)
class VariableBody(BaseModel):
    name: str
    value: str
    kind: str = Field(default="generic", pattern="^(generic|credential)$")


@router.get("/variables")
async def list_variables(svc: Services) -> list[dict[str, Any]]:
    return await svc.secrets.list()


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
async def list_apikeys(svc: Services) -> list[dict[str, Any]]:
    return await svc.apikeys.list()


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
    from lga.services.files import FileTooLargeError

    content = await file.read()
    try:
        return await svc.files.save(
            file.filename or "upload", file.content_type or "application/octet-stream", content
        )
    except FileTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc


@router.get("/files")
async def list_files(svc: Services) -> list[dict[str, Any]]:
    return await svc.files.list()


# ---------------------------------------------------------------- mcp servers (§8.3, §11.7)
class McpServerBody(BaseModel):
    name: str
    transport: str = Field(default="streamable_http", pattern="^(stdio|streamable_http|sse)$")
    config: dict[str, Any] = Field(default_factory=dict)


@router.get("/mcp-servers")
async def list_mcp_servers(svc: Services) -> list[dict[str, Any]]:
    return await svc.mcp_servers.list()


@router.post("/mcp-servers", status_code=201)
async def upsert_mcp_server(body: McpServerBody, svc: Services) -> dict[str, Any]:
    return await svc.mcp_servers.upsert(body.name, body.transport, body.config)


@router.delete("/mcp-servers/{name}", status_code=204)
async def delete_mcp_server(name: str, svc: Services) -> None:
    if not await svc.mcp_servers.delete(name):
        raise HTTPException(404, "mcp server not found")


@router.get("/mcp/config")
async def mcp_client_config(svc: Services) -> dict[str, Any]:
    """Ready-to-paste client JSON (SPEC §8.1)."""
    return {
        "mcpServers": {
            "lga": {
                "type": "http",
                "url": f"{svc.settings.host_url}/mcp",
                **(
                    {"headers": {"X-API-Key": "<your lga_sk_… key with mcp:invoke scope>"}}
                    if svc.settings.auth_enabled
                    else {}
                ),
            }
        }
    }


# ---------------------------------------------------------------- misc (§9.8)
misc_router = APIRouter(tags=["misc"])


@misc_router.get("/health")
async def health(svc: Services) -> dict[str, Any]:
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
    status = "ok" if db_ok and checkpointer_ok else "degraded"
    return {
        "status": status,
        "db": db_ok,
        "checkpointer": checkpointer_ok,
        "tier": svc.settings.storage_tier,
    }


@misc_router.get("/version")
async def version(svc: Services) -> dict[str, Any]:
    import langgraph

    import lga as lga_pkg

    try:
        from a2a.utils.constants import DEFAULT_PROTOCOL_VERSION  # type: ignore

        protocol = DEFAULT_PROTOCOL_VERSION
    except Exception:
        protocol = "0.3.x"
    return {
        "lga": lga_pkg.__version__,
        "a2a_protocol": protocol,
        "langgraph": getattr(langgraph, "__version__", "unknown"),
        "db_backend": svc.settings.storage_tier,
    }


@misc_router.get("/config", dependencies=[StudioAuth])
async def config(svc: Services) -> dict[str, Any]:
    data = svc.settings.model_dump(mode="json")
    data["secret_key"] = "***" if svc.settings.secret_key else ""
    return data


# files need token-only access (A2A FileParts) — outside StudioAuth
public_files_router = APIRouter(tags=["files"])


@public_files_router.get("/files/{file_id}")
async def download_file(
    file_id: str, svc: Services, token: str = Query(default="")
) -> Response:
    found = await svc.files.get(file_id, token=token or None)
    if found is None:
        raise HTTPException(404, "file not found")
    row, content = found
    return Response(
        content=content,
        media_type=row.mime,
        headers={"Content-Disposition": f'inline; filename="{row.name}"'},
    )
