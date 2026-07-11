"""First-class serving surface `serving.mode` + legacy migration (SPEC §5.2).

A published flow is an A2A agent XOR an MCP tool XOR a plain REST API — never two
at once. The active surface is the single field `FlowMeta.serving.mode`; the old
`a2a.enabled`/`mcp.enabled` booleans are kept derived-in-sync for wire/frontend
compatibility, so a conflicting pair is structurally impossible.
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
    assert meta.serve_mode == "a2a"
    assert meta.serving.mode == "a2a"
    assert meta.a2a.enabled is True
    assert meta.mcp.enabled is False  # derived from the single source of truth


def test_mcp_only_is_mcp_mode() -> None:
    meta = FlowMeta(name="x", slug="x", mcp=McpSettings(enabled=True, description="t"))
    assert meta.serve_mode == "mcp"
    assert meta.serving.mode == "mcp"
    assert meta.a2a.enabled is False


def test_neither_enabled_is_api_mode() -> None:
    meta = FlowMeta(name="x", slug="x")
    assert meta.serve_mode == "api"
    assert meta.serving.mode == "api"
    assert meta.a2a.enabled is False
    assert meta.mcp.enabled is False


def test_a2a_only_is_a2a_mode() -> None:
    meta = FlowMeta(name="x", slug="x", a2a=A2ASettings(enabled=True, description="d"))
    assert meta.serve_mode == "a2a"
    assert meta.serving.mode == "a2a"
    assert meta.mcp.enabled is False


def test_legacy_dict_spec_migrates_to_serving_mode() -> None:
    # a spec loaded from JSON (no `serving` key) is lifted deterministically
    meta = FlowMeta.model_validate(
        {"name": "x", "slug": "x", "a2a": {"enabled": True, "description": "d"}}
    )
    assert meta.serving.mode == "a2a"
    assert meta.a2a.enabled is True
    assert meta.mcp.enabled is False


def test_explicit_serving_mode_wins_over_legacy_booleans() -> None:
    # when `serving` is present it is authoritative; legacy booleans are re-derived
    meta = FlowMeta.model_validate(
        {
            "name": "x",
            "slug": "x",
            "serving": {"mode": "mcp"},
            "a2a": {"enabled": True, "description": "d"},
            "mcp": {"description": "t"},
        }
    )
    assert meta.serve_mode == "mcp"
    assert meta.a2a.enabled is False
    assert meta.mcp.enabled is True
