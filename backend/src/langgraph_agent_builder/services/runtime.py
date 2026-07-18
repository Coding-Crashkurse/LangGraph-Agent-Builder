"""Gateway to the agentplane runtime API (via ``agentplane_sdk.RuntimeClient``).

The builder talks to the runtime API only — through the gateway, with the
caller's token. Local validation is advisory; the runtime's answer is
authoritative. This module is the single place that touches the SDK client.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import httpx
from agentplane_core import DeploymentInfo, FlowDefinition, Resource, ValidationResult
from agentplane_sdk import (
    AuthError,
    NotFoundError,
    RuntimeClient,
    TransportError,
    ValidationFailedError,
)
from agentplane_sdk import ConflictError as RuntimeConflictError
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from langgraph_agent_builder.errors import (
    ConflictError,
    InvalidDefinitionError,
    RuntimeRejectedError,
    RuntimeUnavailableError,
)
from langgraph_agent_builder.errors import (
    NotFoundError as BuilderNotFoundError,
)
from langgraph_agent_builder.services.settings import Settings

_RESOURCE_ADAPTER: TypeAdapter[Resource] = TypeAdapter(Resource)

ResourceGroup = Literal["model_provider", "vector_db", "mcp_server"]

_GROUP_BY_KIND: dict[str, ResourceGroup] = {
    "model_provider": "model_provider",
    "pgvector": "vector_db",
    "qdrant": "vector_db",
    "mcp_server": "mcp_server",
}


class ResourceSummary(BaseModel):
    """Names + kinds only — the builder never sees resource credentials."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: str
    group: ResourceGroup
    display_name: str = ""


class RuntimeHealth(BaseModel):
    """Liveness of the configured agentplane runtime (for the status indicator)."""

    model_config = ConfigDict(frozen=True)

    configured: bool
    reachable: bool


class RuntimeGateway:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return bool(self._settings.runtime_url)

    def _client(self, token: str | None) -> RuntimeClient:
        return RuntimeClient(self._settings.runtime_url, token or None)

    async def validate(self, raw: Mapping[str, Any], token: str | None) -> ValidationResult | None:
        """Stateful runtime validation; ``None`` when the runtime was not asked.

        The Validate button must stay useful offline, so an unreachable (or
        unauthorized) runtime degrades to local-only results instead of
        failing the request.
        """
        if not self.configured:
            return None
        async with self._client(token) as client:
            try:
                return await client.validate(dict(raw))
            except (TransportError, AuthError):
                return None

    async def publish(
        self, defn: FlowDefinition, token: str | None, *, version_label: str | None = None
    ) -> DeploymentInfo:
        """Update the runtime draft (create when missing) and deploy it."""
        self._require_configured()
        async with self._client(token) as client:
            try:
                try:
                    await client.update_draft(defn.name, defn)
                except NotFoundError:
                    await client.create_draft(defn)
                return await client.deploy(defn.name, version_label=version_label)
            except ValidationFailedError as exc:
                raise RuntimeRejectedError(
                    "runtime rejected the definition", list(exc.result.issues)
                ) from exc
            except TransportError as exc:
                raise RuntimeUnavailableError(f"runtime unreachable: {exc}") from exc

    async def playground(self, defn: FlowDefinition, token: str | None) -> DeploymentInfo:
        """Sync the draft and deploy it ephemerally (served under /a2a/_draft/)."""
        self._require_configured()
        async with self._client(token) as client:
            try:
                try:
                    await client.update_draft(defn.name, defn)
                except NotFoundError:
                    await client.create_draft(defn)
                return await client.deploy(defn.name, ephemeral=True)
            except ValidationFailedError as exc:
                raise RuntimeRejectedError(
                    "runtime rejected the definition", list(exc.result.issues)
                ) from exc
            except TransportError as exc:
                raise RuntimeUnavailableError(f"runtime unreachable: {exc}") from exc

    async def list_resources(
        self, group: ResourceGroup | None, token: str | None
    ) -> list[ResourceSummary]:
        self._require_configured()
        async with self._client(token) as client:
            try:
                resources = await client.list_resources()
            except TransportError as exc:
                raise RuntimeUnavailableError(f"runtime unreachable: {exc}") from exc
        summaries = [
            ResourceSummary(
                name=r.name,
                kind=r.kind,
                group=_GROUP_BY_KIND.get(r.kind, "mcp_server"),
                display_name=r.display_name,
            )
            for r in resources
        ]
        if group is None:
            return summaries
        return [s for s in summaries if s.group == group]

    async def create_resource(self, raw: Mapping[str, Any], token: str | None) -> ResourceSummary:
        """Create a resource ON THE RUNTIME (thin proxy, SPEC §3).

        Credentials in the payload pass through write-only: the runtime stores
        them Fernet-encrypted; the builder never persists or returns them.
        """
        self._require_configured()
        try:
            resource = _RESOURCE_ADAPTER.validate_python(dict(raw))
        except ValidationError as exc:
            raise InvalidDefinitionError(
                f"invalid resource: {'; '.join(e['msg'] for e in exc.errors()[:3])}"
            ) from exc
        async with self._client(token) as client:
            try:
                created = await client.create_resource(resource)
            except ValidationFailedError as exc:
                raise RuntimeRejectedError(
                    "runtime rejected the resource", list(exc.result.issues)
                ) from exc
            except RuntimeConflictError as exc:
                raise ConflictError(str(exc)) from exc
            except TransportError as exc:
                raise RuntimeUnavailableError(f"runtime unreachable: {exc}") from exc
        return ResourceSummary(
            name=created.name,
            kind=created.kind,
            group=_GROUP_BY_KIND.get(created.kind, "mcp_server"),
            display_name=created.display_name,
        )

    async def remove_from_platform(self, name: str, token: str | None) -> None:
        """Undeploy the flow (deregisters it) and delete the runtime definition.

        Best-effort semantics: "not deployed" and "not found" count as success —
        the goal is absence. The runtime enforces authorization; an unreachable
        runtime raises so the caller's local delete does not proceed silently.
        """
        self._require_configured()
        async with self._client(token) as client:
            try:
                await client.undeploy(name)
            except (BuilderNotFoundError, NotFoundError, RuntimeConflictError):
                pass  # never published, already gone, or not deployed
            except TransportError as exc:
                raise RuntimeUnavailableError(f"runtime unreachable: {exc}") from exc
            try:
                await client.delete(name)
            except (BuilderNotFoundError, NotFoundError):
                pass
            except TransportError as exc:
                raise RuntimeUnavailableError(f"runtime unreachable: {exc}") from exc

    async def delete_resource(self, name: str, token: str | None) -> None:
        """Delete a resource on the runtime (refused there while referenced)."""
        self._require_configured()
        async with self._client(token) as client:
            try:
                await client.delete_resource(name)
            except NotFoundError as exc:
                raise BuilderNotFoundError(f"resource {name!r} not found") from exc
            except RuntimeConflictError as exc:
                raise ConflictError(str(exc)) from exc
            except TransportError as exc:
                raise RuntimeUnavailableError(f"runtime unreachable: {exc}") from exc

    async def health(self, token: str | None) -> RuntimeHealth:
        """Probe the runtime's unauthenticated ``/healthz`` (short timeout).

        Advisory only — a red dot never blocks editing; it just tells the user
        upfront whether publish and resource management can work right now.
        """
        if not self.configured:
            return RuntimeHealth(configured=False, reachable=False)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        url = self._settings.runtime_url.rstrip("/") + "/healthz"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError:
            return RuntimeHealth(configured=True, reachable=False)
        return RuntimeHealth(configured=True, reachable=response.is_success)

    def _require_configured(self) -> None:
        if not self.configured:
            raise RuntimeUnavailableError(
                "no runtime configured — set BUILDER_RUNTIME_URL to the gateway URL"
            )
