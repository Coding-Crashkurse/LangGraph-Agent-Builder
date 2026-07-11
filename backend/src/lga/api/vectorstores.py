"""Vector store connections & collections API (SPEC §9.9, §8b.3)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lga.api.deps import Services, StudioAuth
from lga.vectorstores import BACKEND_EXTRAS, installed_backends

router = APIRouter(prefix="/vectorstores", tags=["vectorstores"], dependencies=[StudioAuth])


class ConnectionBody(BaseModel):
    name: str
    backend: str = "local"
    config: dict[str, Any] = Field(default_factory=dict)


class CollectionBody(BaseModel):
    name: str
    dim: int = 32
    metric: Literal["cosine", "l2", "ip"] = "cosine"  # typo → 422, not a backend error


@router.get("/backends")
async def list_backends() -> dict[str, Any]:
    return {"installed": installed_backends(), "all": list(BACKEND_EXTRAS)}


@router.get("")
async def list_connections(svc: Services) -> list[dict[str, Any]]:
    conns: list[dict[str, Any]] = await svc.vectorstores.list_with_health()
    return conns


@router.post("", status_code=201)
async def create_connection(body: ConnectionBody, svc: Services) -> dict[str, Any]:
    if body.backend not in BACKEND_EXTRAS:
        raise HTTPException(422, f"unknown backend {body.backend!r}")
    created: dict[str, Any] = await svc.vectorstores.upsert(body.name, body.backend, body.config)
    return created


@router.delete("/{name}", status_code=204)
async def delete_connection(name: str, svc: Services) -> None:
    if not await svc.vectorstores.delete(name):
        raise HTTPException(404, "connection not found")


@router.get("/{name}/collections")
async def list_collections(name: str, svc: Services) -> list[dict[str, Any]]:
    try:
        provider = await svc.vectorstores.provider(name)
    except KeyError as exc:
        raise HTTPException(404, "connection not found") from exc
    try:
        return [c.model_dump() for c in await provider.list_collections()]
    except Exception as exc:
        raise HTTPException(502, f"backend error: {exc}") from exc


@router.post("/{name}/collections", status_code=201)
async def create_collection(name: str, body: CollectionBody, svc: Services) -> dict[str, Any]:
    try:
        provider = await svc.vectorstores.provider(name)
    except KeyError as exc:
        raise HTTPException(404, "connection not found") from exc
    try:
        await provider.ensure_collection(body.name, body.dim, body.metric)
    except Exception as exc:
        raise HTTPException(502, f"backend error: {exc}") from exc
    return {"name": body.name, "dim": body.dim, "metric": body.metric}
