"""Unit tests for lga.components.tools.mcp_toolset.

`_connection_from_config` is pure; `load_mcp_tools` / provide_tools / health_check
are exercised with an in-repo fake MCP client substituted for the real one.
"""

from __future__ import annotations

from typing import Any

import pytest

from lga.components.tools.mcp_toolset import (
    MCPToolset,
    _connection_from_config,
    load_mcp_tools,
)
from lga.sdk.testing import ComponentTestHarness

# ------------------------------------------------------------------- _connection_from_config


def test_connection_streamable_http_with_headers() -> None:
    conn = _connection_from_config(
        {"transport": "streamable_http", "url": "http://x/mcp", "headers": {"A": "b"}}
    )
    assert conn == {"transport": "streamable_http", "url": "http://x/mcp", "headers": {"A": "b"}}


def test_connection_sse_without_headers() -> None:
    conn = _connection_from_config({"transport": "sse", "url": "http://x/sse"})
    assert conn == {"transport": "sse", "url": "http://x/sse"}
    assert "headers" not in conn


def test_connection_stdio_with_env_and_args() -> None:
    conn = _connection_from_config(
        {"transport": "stdio", "command": "srv", "args": ["--x"], "env": {"K": "V"}}
    )
    assert conn == {"transport": "stdio", "command": "srv", "args": ["--x"], "env": {"K": "V"}}


def test_connection_unknown_transport_defaults_to_stdio() -> None:
    conn = _connection_from_config({"transport": "weird", "command": "c"})
    assert conn["transport"] == "stdio"
    assert conn["command"] == "c"
    assert conn["args"] == []
    assert "env" not in conn


def test_connection_header_forwarding_injects_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LGA_FWD_API_KEY", "secret123")
    conn = _connection_from_config(
        {"transport": "streamable_http", "url": "http://x", "header_forwarding": True}
    )
    assert conn["headers"] == {"X-API-Key": "secret123"}


def test_connection_header_forwarding_keeps_explicit_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LGA_FWD_API_KEY", "secret123")
    conn = _connection_from_config(
        {
            "transport": "streamable_http",
            "url": "http://x",
            "header_forwarding": True,
            "headers": {"X-API-Key": "orig"},
        }
    )
    assert conn["headers"]["X-API-Key"] == "orig"


def test_connection_header_forwarding_off_without_env() -> None:
    conn = _connection_from_config({"transport": "streamable_http", "url": "http://x"})
    assert "headers" not in conn


def test_connection_header_forwarding_on_but_no_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LGA_FWD_API_KEY", raising=False)
    conn = _connection_from_config(
        {"transport": "streamable_http", "url": "http://x", "header_forwarding": True}
    )
    assert "headers" not in conn


# --------------------------------------------------------------------------- fake MCP client


class _FakeTool:
    def __init__(
        self, name: str, description: str = "", args: dict[str, Any] | None = None
    ) -> None:
        self.name = name
        self.description = description
        self.args = args or {}


class _FakeMCPClient:
    last_connections: dict[str, Any] = {}

    def __init__(self, connections: dict[str, Any]) -> None:
        _FakeMCPClient.last_connections = connections

    async def get_tools(self) -> list[_FakeTool]:
        return [
            _FakeTool("add", "adds", {"type": "object"}),
            _FakeTool("sub", "subtracts"),
        ]


def _install_fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", _FakeMCPClient)


# --------------------------------------------------------------------------- load_mcp_tools


async def test_load_mcp_tools_converts_all(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch)
    defs = await load_mcp_tools({"transport": "streamable_http", "url": "http://x"})
    assert {d.name for d in defs} == {"add", "sub"}
    add = next(d for d in defs if d.name == "add")
    assert add.description == "adds"
    assert add.args_schema == {"type": "object"}
    assert add.callable_ref is not None


async def test_load_mcp_tools_respects_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch)
    defs = await load_mcp_tools(
        {"transport": "streamable_http", "url": "http://x", "tools": ["add"]}
    )
    assert [d.name for d in defs] == ["add"]


async def test_load_mcp_tools_passes_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch)
    await load_mcp_tools({"transport": "sse", "url": "http://x/sse"})
    assert _FakeMCPClient.last_connections["toolset"]["url"] == "http://x/sse"


# --------------------------------------------------------------------------- provide_tools / health


async def test_provide_tools_returns_lazy_toolset(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch)
    ctx = (
        ComponentTestHarness()
        .build(MCPToolset, config={"transport": "streamable_http", "url": "http://x"})
        .ctx
    )
    lazy = MCPToolset().provide_tools(ctx)
    tools = await lazy.resolve()
    assert {t.name for t in tools} == {"add", "sub"}


async def test_health_check_lists_from_configured_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch)
    ctx = (
        ComponentTestHarness()
        .build(MCPToolset, config={"transport": "streamable_http", "url": "http://health"})
        .ctx
    )
    await MCPToolset().health_check(ctx)
    assert _FakeMCPClient.last_connections["toolset"]["url"] == "http://health"


def test_on_field_change_updates_config() -> None:
    original = {"url": "a"}
    updated = MCPToolset().on_field_change(original, "transport", "sse")
    assert updated["transport"] == "sse"
    assert updated["url"] == "a"
    assert "transport" not in original  # copy, not mutation


async def test_mcp_toolset_node_is_noop() -> None:
    node = ComponentTestHarness().build(MCPToolset, config={"transport": "streamable_http"})
    assert await node() == {}
