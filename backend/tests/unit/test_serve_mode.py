"""Exclusive serving surfaces + serve_mode (SPEC §7.1/§8.1).

A published flow is an A2A agent XOR an MCP tool XOR a plain REST API — never
two at once. A2A takes precedence if a spec somehow enables both.
"""

from __future__ import annotations

from langgraph_agent_builder.schema.flowspec import A2ASettings, FlowMeta, McpSettings


def test_both_enabled_a2a_wins_mcp_forced_off() -> None:
    meta = FlowMeta(
        name="x",
        slug="x",
        a2a=A2ASettings(enabled=True, description="d"),
        mcp=McpSettings(enabled=True, description="t"),
    )
    assert meta.a2a.enabled is True
    assert meta.mcp.enabled is False
    assert meta.serve_mode == "a2a"


def test_mcp_only_is_mcp_mode() -> None:
    meta = FlowMeta(name="x", slug="x", mcp=McpSettings(enabled=True, description="t"))
    assert meta.serve_mode == "mcp"
    assert meta.a2a.enabled is False


def test_neither_enabled_is_api_mode() -> None:
    meta = FlowMeta(name="x", slug="x")
    assert meta.a2a.enabled is False
    assert meta.mcp.enabled is False
    assert meta.serve_mode == "api"


def test_a2a_only_is_a2a_mode() -> None:
    meta = FlowMeta(name="x", slug="x", a2a=A2ASettings(enabled=True, description="d"))
    assert meta.serve_mode == "a2a"
    assert meta.mcp.enabled is False
