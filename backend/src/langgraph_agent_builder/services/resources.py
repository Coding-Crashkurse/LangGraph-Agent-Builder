"""Resources layer — long-lived, panel-managed config referenced by name.

A second config plane beside the flow canvas: a FlowSpec references a resource
via ``{"$resource": "<name>"}`` (see ``sdk.fields.ResourceRefInput`` /
``sdk.ports.ResourceHandle``), never by credentials, so flows stay portable.

Four resource types: ``model_provider``, ``knowledge_base``, ``mcp_server``,
``a2a_agent``. ``mcp_server`` reuses the existing ``mcp_servers`` table (via
:class:`McpServersService`) rather than duplicating storage; the other three
have dedicated rows. Credential params are ``$secret`` refs — never plaintext —
and are only resolved (:meth:`_resolve_params`) for live health probes, never
returned by :meth:`_info`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from langgraph_agent_builder.db.models import (
    A2AAgentRow,
    KnowledgeBaseRow,
    ModelProviderRow,
    utcnow,
)
from langgraph_agent_builder.schema.diagnostics import DiagnosticCode

if TYPE_CHECKING:
    from langgraph_agent_builder.services.mcp_servers import McpServersService
    from langgraph_agent_builder.services.secrets import SecretsService
    from langgraph_agent_builder.services.settings import Settings
    from langgraph_agent_builder.services.vectorstores import VectorStoreService

logger = logging.getLogger("langgraph_agent_builder.services.resources")

# Resource lookup tokens are ``"<resource_type><SEP><version>"`` — MUST match
# ``compiler.resolve._RESOURCE_SEP`` so the resolver can recover the type.
_RESOURCE_SEP = "#"

# The three resource types backed by dedicated rows; ``mcp_server`` is delegated.
# No shared mixin (SPEC: clone the column set inline), so these structurally
# identical rows have no common typed supertype beyond Base — dispatched by
# string, hence ``type[Any]``.
_ROW_TYPES: dict[str, type[Any]] = {
    "model_provider": ModelProviderRow,
    "knowledge_base": KnowledgeBaseRow,
    "a2a_agent": A2AAgentRow,
}
RESOURCE_TYPES: tuple[str, ...] = (*_ROW_TYPES.keys(), "mcp_server")


def _version_token(config: dict[str, Any]) -> str:
    """A short, stable hash of a resource's config — folded into the compile
    cache key so editing a resource (model list, KB collection, cached A2A
    card, …) invalidates stale compiles."""
    blob = json.dumps(config, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def _resource_key_type(token: str) -> str:
    """Recover the resource type from a :meth:`names_with_types` token
    (``"<type>#<version>"``) — the producer-side mirror of
    ``compiler.resolve._resource_type``."""
    return token.split(_RESOURCE_SEP, 1)[0]


class ResourcesService:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        secrets: SecretsService,
        mcp_servers: McpServersService,
        vectorstores: VectorStoreService,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._secrets = secrets
        self._mcp = mcp_servers
        self._vectorstores = vectorstores

    # ------------------------------------------------------------------ crud
    async def list(self, rtype: str) -> list[dict[str, Any]]:
        self._require_type(rtype)
        if rtype == "mcp_server":
            return [self._info_from_mcp(s) for s in await self._mcp.list()]
        model = _ROW_TYPES[rtype]
        async with self._sessions() as session:
            rows = (await session.execute(select(model))).scalars().all()
        return [self._info(rtype, r) for r in rows]

    async def get(self, rtype: str, name: str) -> dict[str, Any] | None:
        self._require_type(rtype)
        if rtype == "mcp_server":
            server = await self._mcp.get(name)
            return self._info_from_mcp(server) if server else None
        model = _ROW_TYPES[rtype]
        async with self._sessions() as session:
            row = (
                await session.execute(select(model).where(model.name == name))
            ).scalar_one_or_none()
        return self._info(rtype, row) if row else None

    async def upsert(self, rtype: str, name: str, config: dict[str, Any]) -> dict[str, Any]:
        self._require_type(rtype)
        if rtype == "mcp_server":
            transport = str(config.get("transport") or "streamable_http")
            cfg = {k: v for k, v in config.items() if k != "transport"}
            return self._info_from_mcp(await self._mcp.upsert(name, transport, cfg))
        model = _ROW_TYPES[rtype]
        async with self._sessions() as session:
            row = (
                await session.execute(select(model).where(model.name == name))
            ).scalar_one_or_none()
            if row is None:
                row = model(name=name)
                session.add(row)
            row.config = config
            await session.commit()
            await session.refresh(row)
        return self._info(rtype, row)

    async def delete(self, rtype: str, name: str) -> bool:
        self._require_type(rtype)
        if rtype == "mcp_server":
            return await self._mcp.delete(name)
        model = _ROW_TYPES[rtype]
        async with self._sessions() as session:
            result = await session.execute(delete(model).where(model.name == name))
            await session.commit()
        return bool(cast("CursorResult[Any]", result).rowcount)

    # ------------------------------------------------------------------ runtime resolution
    async def resolved_config(self, rtype: str, name: str) -> dict[str, Any] | None:
        """Resource config with ``$secret``/``$var`` refs resolved to concrete
        values — for in-process node construction at build/run time (model
        providers, knowledge bases).

        Returns ``None`` when the resource does not exist. Unlike :meth:`get`
        (whose :meth:`_info` deliberately keeps credentials as ``{"$secret":
        name}`` refs so the API never leaks them), this resolves them via
        :meth:`_resolve_params`; the result therefore must stay in-process and is
        never returned over the wire (SPEC §10.5)."""
        info = await self.get(rtype, name)
        if info is None:
            return None
        return await self._resolve_params(info["config"])

    # ------------------------------------------------------------------ resolver lookup
    async def names_with_types(self) -> dict[str, str]:
        """``{name: "<type>#<version>"}`` across all four types — the resolver
        lookup for ``{"$resource": name}`` (E016 existence, E017 type check) and
        the version-aware compile-cache digest."""
        out: dict[str, str] = {}
        for rtype in RESOURCE_TYPES:
            for info in await self.list(rtype):
                out[info["name"]] = f"{info['resource_type']}{_RESOURCE_SEP}{info['version']}"
        return out

    # ------------------------------------------------------------------ health
    async def health(self, rtype: str, name: str) -> dict[str, Any]:
        info = await self.get(rtype, name)
        if info is None:
            return {"ok": False, "error": f"resource {name!r} not found", "code": None}
        config = info["config"]
        if rtype == "model_provider":
            return await self._health_model_provider(config)
        if rtype == "knowledge_base":
            return await self._health_knowledge_base(config)
        if rtype == "mcp_server":
            return await self._health_mcp_server(config)
        if rtype == "a2a_agent":
            return await self._health_a2a_agent(name, config)
        return {"ok": False, "error": f"unknown resource type {rtype!r}", "code": None}

    async def _health_model_provider(self, config: dict[str, Any]) -> dict[str, Any]:
        """Best-effort auth preflight → E906. A real network auth probe is
        intentionally skipped (offline/CI safety); a missing credential for a
        provider that requires one is the deterministic failure we surface."""
        params = await self._resolve_params(config)
        provider = str(params.get("provider", "")).lower()
        if provider in ("", "fake", "echo", "ollama"):  # no hosted credential required
            return {"ok": True, "error": None, "code": None}
        if provider in ("openai", "anthropic") and not params.get("api_key"):
            return {
                "ok": False,
                "error": f"{provider} provider requires an api_key",
                "code": DiagnosticCode.E906.value,
            }
        return {"ok": True, "error": None, "code": None}

    async def _health_knowledge_base(self, config: dict[str, Any]) -> dict[str, Any]:
        """Delegate to the referenced vector store connection → E902/E903/E904."""
        from langgraph_agent_builder.vectorstores.base import (
            CollectionMissing,
            DimensionMismatch,
            VectorStoreError,
        )

        connection = str(config.get("vectorstore") or "")
        collection = str(config.get("collection") or "")
        if not connection or not collection:
            return {
                "ok": False,
                "error": "knowledge base needs a vectorstore connection and collection",
                "code": None,
            }
        try:
            await self._vectorstores.check_collection(connection, collection)
        except CollectionMissing as exc:
            return {"ok": False, "error": str(exc), "code": DiagnosticCode.E903.value}
        except DimensionMismatch as exc:
            return {"ok": False, "error": str(exc), "code": DiagnosticCode.E904.value}
        except (VectorStoreError, KeyError) as exc:
            return {"ok": False, "error": str(exc), "code": DiagnosticCode.E902.value}
        return {"ok": True, "error": None, "code": None}

    async def _health_mcp_server(self, config: dict[str, Any]) -> dict[str, Any]:
        """List tools over streamable_http/sse → E905. stdio is never spawned
        for a health probe (Windows selector loop / SPEC machine constraint)."""
        transport = str(config.get("transport") or "streamable_http")
        if transport == "stdio":
            return {
                "ok": False,
                "error": "stdio transport is not health-probed (streamable_http only)",
                "code": DiagnosticCode.E905.value,
            }
        resolved = await self._resolve_params(config)
        try:
            from langgraph_agent_builder.components.tools.mcp_toolset import load_mcp_tools

            await load_mcp_tools(resolved)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "code": DiagnosticCode.E905.value}
        return {"ok": True, "error": None, "code": None}

    async def _health_a2a_agent(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        """Re-fetch + validate the remote AgentCard (SSRF-guarded) → E907, then
        cache the card back onto the resource (staleness feeds the version)."""
        try:
            card = await self._fetch_card(config)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "code": DiagnosticCode.E907.value}
        stored = {k: v for k, v in config.items() if k not in ("card", "fetched_at")}
        await self.upsert(
            "a2a_agent", name, {**stored, "card": card, "fetched_at": utcnow().isoformat()}
        )
        return {"ok": True, "error": None, "code": None, "card": card}

    async def _fetch_card(self, config: dict[str, Any]) -> dict[str, Any]:
        import httpx
        from a2a.types import AgentCard

        from langgraph_agent_builder.a2a.push import validate_webhook_url

        url = str(config.get("url") or "")
        if not url:
            raise ValueError("a2a agent resource needs a url")
        card_url = (
            url if url.endswith(".json") else url.rstrip("/") + "/.well-known/agent-card.json"
        )
        validate_webhook_url(card_url, self._settings)  # SSRF guard (§7.9/§10.5)
        params = await self._resolve_params(config)
        headers: dict[str, str] = {}
        auth = params.get("auth")
        if auth:
            headers["Authorization"] = f"Bearer {auth}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(card_url, headers=headers)
            resp.raise_for_status()
            card = AgentCard.model_validate(resp.json())
        dumped: dict[str, Any] = card.model_dump(mode="json", exclude_none=True)
        return dumped

    # ------------------------------------------------------------------ secrets / info
    async def _resolve_params(self, params: dict[str, Any]) -> dict[str, Any]:
        variables, secrets = await self._secrets.snapshot()
        out: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, dict) and "$secret" in value:
                out[key] = secrets.get(value["$secret"], "")
            elif isinstance(value, dict) and "$var" in value:
                out[key] = variables.get(value["$var"], "")
            else:
                out[key] = value
        return out

    @staticmethod
    def _info(rtype: str, row: Any) -> dict[str, Any]:
        # credential params stay as {"$secret": name} refs — never returned raw
        config = dict(row.config or {})
        return {
            "id": row.id,
            "name": row.name,
            "resource_type": rtype,
            "config": config,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "version": _version_token(config),
        }

    @staticmethod
    def _info_from_mcp(server: dict[str, Any]) -> dict[str, Any]:
        # adapt the McpServersService shape into the uniform resource shape;
        # transport folds into config so a transport change bumps the version
        config = {
            "transport": server.get("transport", "streamable_http"),
            **(server.get("config") or {}),
        }
        created = server.get("created_at")
        return {
            "id": server["id"],
            "name": server["name"],
            "resource_type": "mcp_server",
            "config": config,
            "created_at": created,
            "updated_at": created,  # McpServersService._info exposes only created_at
            "version": _version_token(config),
        }

    def _require_type(self, rtype: str) -> None:
        if rtype not in RESOURCE_TYPES:
            raise ValueError(f"unknown resource type {rtype!r}")

    # ------------------------------------------------------------------ boot provisioning
    async def provision(self) -> None:
        """Upsert ``LAB_RESOURCE_<NAME>`` descriptors at boot (deploy parity).

        Each descriptor is ``{"type": "<resource_type>", "config": {...}}``;
        unknown types and failing upserts are skipped, never fatal."""
        for name, descriptor in self._settings.resource_env_definitions().items():
            rtype = str(descriptor.get("type") or descriptor.get("resource_type") or "")
            if rtype not in RESOURCE_TYPES:
                logger.warning("skipping LAB_RESOURCE_%s: unknown type %r", name, rtype)
                continue
            config = dict(descriptor.get("config") or {})
            try:
                await self.upsert(rtype, name, config)
            except Exception:  # pragma: no cover - best-effort provisioning
                logger.exception("failed to provision resource %s (%s)", name, rtype)
