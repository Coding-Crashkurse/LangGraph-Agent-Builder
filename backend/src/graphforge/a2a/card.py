"""AgentCard assembly from flow metadata (CLAUDE.md §9.3).

The card is built from the user-editable AgentCardSpec plus derived fields
(url, version, capabilities, transports). Protocol types come from a2a.types —
never hand-rolled."""

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    TransportProtocol,
)

from graphforge.compiler.spec import FlowSpec
from graphforge.settings import Settings


def a2a_url(settings: Settings, slug: str) -> str:
    return f"{settings.base_url}/serve/a2a/{slug}"


def rest_url(settings: Settings, slug: str) -> str:
    return f"{settings.base_url}/serve/rest/{slug}"


def mcp_url(settings: Settings, slug: str) -> str:
    return f"{settings.base_url}/serve/mcp/{slug}"


def build_agent_card(spec: FlowSpec, settings: Settings, *, include_rest: bool) -> AgentCard:
    card_spec = spec.publish.agent_card
    # Trailing slash is deliberate: the JSON-RPC endpoint lives at the mount
    # root, and Starlette mounts 307-redirect the slash-less prefix (which
    # POSTing A2A clients do not follow).
    url = a2a_url(settings, spec.slug) + "/"

    interfaces = [AgentInterface(transport=TransportProtocol.jsonrpc, url=url)]
    if include_rest:
        interfaces.append(
            AgentInterface(transport=TransportProtocol.http_json, url=rest_url(settings, spec.slug))
        )

    skills = [
        AgentSkill(
            id=skill.id,
            name=skill.name or skill.id,
            description=skill.description,
            tags=skill.tags,
            examples=skill.examples or None,
        )
        for skill in card_spec.skills
    ]

    provider = None
    if card_spec.provider_organization:
        provider = AgentProvider(
            organization=card_spec.provider_organization,
            url=card_spec.provider_url or settings.base_url,
        )

    return AgentCard(
        name=card_spec.name or spec.name,
        description=card_spec.description or spec.description or spec.name,
        url=url,
        version=str(spec.version),
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=card_spec.default_input_modes,
        default_output_modes=card_spec.default_output_modes,
        skills=skills,
        provider=provider,
        preferred_transport=TransportProtocol.jsonrpc,
        additional_interfaces=interfaces,
    )
