"""AgentCard generation (SPEC §7.3, §7.4) — derived, never hand-edited.

a2a-sdk 1.x AgentCard is a protobuf message (protocol v1.0): the single
top-level ``url``/``preferred_transport`` pair is replaced by
``supported_interfaces[]`` (``AgentInterface{url, protocol_binding,
protocol_version}``) and ``capabilities.extended_agent_card`` replaces the old
``supports_authenticated_extended_card`` flag.
"""

from __future__ import annotations

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentProvider,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH, PROTOCOL_VERSION_1_0, TransportProtocol

from langgraph_agent_builder.schema.flowspec import FlowSpec
from langgraph_agent_builder.services.settings import Settings

WELL_KNOWN_PATH = AGENT_CARD_WELL_KNOWN_PATH  # only agent-card.json in v1.0 (agent.json gone)


def agent_url(settings: Settings, slug: str) -> str:
    """Base URL of the flow's HTTP+JSON interface; REST paths (``/message:send``,
    ``/tasks/{id}``, …) hang off it."""
    return f"{settings.host_url}/a2a/{slug}"


def build_card(spec: FlowSpec, semver: str, settings: Settings) -> AgentCard:
    a2a = spec.flow.a2a
    slug = spec.flow.slug
    description = a2a.description or spec.flow.description or spec.flow.name
    name = a2a.agent_name or spec.flow.name

    card = AgentCard(
        name=name,
        description=description,
        version=semver,
        provider=AgentProvider(
            organization=settings.a2a_provider_org, url=settings.a2a_provider_url
        ),
        capabilities=AgentCapabilities(
            streaming=True,
            push_notifications=a2a.push_notifications,
            # §7.5: v1 serves the same card as the public one — flip this later
            # to diverge the authenticated extended card without protocol changes
            extended_agent_card=True,
        ),
        default_input_modes=list(a2a.input_modes or ["text/plain", "application/json"]),
        default_output_modes=list(a2a.output_modes or ["text/plain", "application/json"]),
    )

    # single HTTP+JSON (REST) interface — no gRPC/JSON-RPC binding advertised
    card.supported_interfaces.add(
        url=agent_url(settings, slug),
        protocol_binding=TransportProtocol.HTTP_JSON.value,
        protocol_version=PROTOCOL_VERSION_1_0,
    )

    skill = card.skills.add(id=slug, name=name, description=description)
    skill.tags.extend(a2a.tags or list(spec.flow.tags))
    if a2a.examples:
        skill.examples.extend(a2a.examples)
    if a2a.input_modes:
        skill.input_modes.extend(a2a.input_modes)
    if a2a.output_modes:
        skill.output_modes.extend(a2a.output_modes)

    if a2a.auth == "api-key":
        scheme = card.security_schemes["apiKey"].api_key_security_scheme
        scheme.name = "X-API-Key"
        scheme.location = "header"
        card.security_requirements.add().schemes["apiKey"]  # empty scope list

    return card
