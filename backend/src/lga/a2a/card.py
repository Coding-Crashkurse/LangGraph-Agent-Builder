"""AgentCard generation (SPEC §7.3, §7.4) — derived, never hand-edited."""

from __future__ import annotations

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentProvider,
    AgentSkill,
    APIKeySecurityScheme,
    In,
    SecurityScheme,
    TransportProtocol,
)

from lga.schema.flowspec import FlowSpec
from lga.services.settings import Settings

WELL_KNOWN_PATH = "/.well-known/agent-card.json"
LEGACY_WELL_KNOWN_PATH = "/.well-known/agent.json"


def agent_url(settings: Settings, slug: str) -> str:
    # Trailing slash is deliberate: the JSON-RPC endpoint lives at the mount
    # root and slash-less prefixes 307-redirect (which POSTing clients don't follow).
    return f"{settings.host_url}/a2a/{slug}/"


def build_card(spec: FlowSpec, semver: str, settings: Settings) -> AgentCard:
    a2a = spec.flow.a2a
    slug = spec.flow.slug
    description = a2a.description or spec.flow.description or spec.flow.name

    skill = AgentSkill(
        id=slug,
        name=a2a.agent_name or spec.flow.name,
        description=description,
        tags=a2a.tags or list(spec.flow.tags),
        examples=a2a.examples or None,
        input_modes=a2a.input_modes or None,
        output_modes=a2a.output_modes or None,
    )

    security_schemes: dict[str, SecurityScheme] | None = None
    security: list[dict[str, list[str]]] | None = None
    if a2a.auth == "api-key":
        security_schemes = {
            "apiKey": SecurityScheme(
                root=APIKeySecurityScheme(type="apiKey", in_=In.header, name="X-API-Key")
            )
        }
        security = [{"apiKey": []}]

    return AgentCard(
        name=a2a.agent_name or spec.flow.name,
        description=description,
        url=agent_url(settings, slug),
        preferred_transport=TransportProtocol.jsonrpc,
        version=semver,
        provider=AgentProvider(
            organization=settings.a2a_provider_org, url=settings.a2a_provider_url
        ),
        capabilities=AgentCapabilities(
            streaming=True,
            push_notifications=a2a.push_notifications,
            state_transition_history=True,
        ),
        default_input_modes=a2a.input_modes or ["text/plain", "application/json"],
        default_output_modes=a2a.output_modes or ["text/plain", "application/json"],
        skills=[skill],
        security_schemes=security_schemes,
        security=security,
    )
