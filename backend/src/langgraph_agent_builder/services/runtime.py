"""Gateway to the agentplane runtime API (via ``agentplane_sdk.RuntimeClient``).

The builder talks to the runtime API only — through the gateway, with the
caller's token. Local validation is advisory; the runtime's answer is
authoritative. This module is the single place that touches the SDK client.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from agentplane_core import DeploymentInfo, FlowDefinition, ValidationResult
from agentplane_sdk import (
    AuthError,
    NotFoundError,
    RuntimeClient,
    TransportError,
    ValidationFailedError,
)
from pydantic import BaseModel, ConfigDict

from langgraph_agent_builder.errors import RuntimeRejectedError, RuntimeUnavailableError
from langgraph_agent_builder.services.settings import Settings

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

    async def publish(self, defn: FlowDefinition, token: str | None) -> DeploymentInfo:
        """Update the runtime draft (create when missing) and deploy it."""
        self._require_configured()
        async with self._client(token) as client:
            try:
                try:
                    await client.update_draft(defn.name, defn)
                except NotFoundError:
                    await client.create_draft(defn)
                return await client.deploy(defn.name)
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

    def _require_configured(self) -> None:
        if not self.configured:
            raise RuntimeUnavailableError(
                "no runtime configured — set BUILDER_RUNTIME_URL to the gateway URL"
            )
