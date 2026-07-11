"""MCP suite (SPEC §15.4): list/call via real mcp client, schema fidelity, E063."""

from __future__ import annotations

import asyncio
import socket
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
import uvicorn

from tests.conftest import approval_spec, hello_spec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from mcp.types import TextContent

    from lga.services.settings import Settings


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return cast("int", sock.getsockname()[1])


@pytest.fixture
async def server(sqlite_settings: Settings) -> AsyncIterator[str]:
    """Real uvicorn server — the mcp client needs actual HTTP."""
    from lga.app import create_app
    from lga.db.migrate import upgrade_async

    port = _free_port()
    sqlite_settings.port = port
    sqlite_settings.host_url = f"http://127.0.0.1:{port}"
    await upgrade_async(sqlite_settings)
    app = create_app(sqlite_settings, backend_only=True)
    app.state.auto_migrate = False
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.get_running_loop().create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await asyncio.wait_for(task, timeout=10)


async def _publish(base: str, spec: dict[str, Any]) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        response = await client.post("/api/v1/flows", json={"spec": spec})
        assert response.status_code == 201, response.text
        flow_id = response.json()["id"]
        response = await client.post(f"/api/v1/flows/{flow_id}/publish", json={"version": "minor"})
        assert response.json()["published"], response.text


async def test_mcp_list_and_call(server: str) -> None:
    spec = hello_spec("mcp-hello")
    spec["flow"]["a2a"] = {"enabled": False}  # MCP mode: serving is exclusive (A2A off)
    spec["flow"]["mcp"] = {
        "enabled": True,
        "tool_name": "say_hello",
        "description": "Scripted greeting tool.",
    }
    await _publish(server, spec)

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{server}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool = next(t for t in tools.tools if t.name == "say_hello")
            assert tool.description == "Scripted greeting tool."
            assert "input_text" in tool.inputSchema.get("properties", {})
            result = await session.call_tool("say_hello", {"input_text": "hi"})
            text = "".join(
                cast("TextContent", c).text
                for c in result.content
                if getattr(c, "type", "") == "text"
            )
            assert "Hello from LGA!" in text


async def test_mcp_tool_name_never_uuid(server: str) -> None:
    spec = hello_spec("mcp-slug")
    spec["flow"]["a2a"] = {"enabled": False}  # MCP mode: serving is exclusive (A2A off)
    spec["flow"]["mcp"] = {"enabled": True, "description": "tool"}
    await _publish(server, spec)
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{server}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert any(t.name == "mcp_slug" for t in tools.tools)


def _json_flow(slug: str) -> dict[str, Any]:
    """start → set_data(json) → end.json — a flow with a structured terminal."""
    return {
        "schema_version": "1",
        "flow": {
            "name": slug,
            "slug": slug,
            "description": "emits json",
            "mcp": {"enabled": True, "tool_name": "make_json", "description": "emits json"},
        },
        "nodes": [
            {
                "id": "start",
                "component_id": "lga.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "sd",
                "component_id": "lga.io.set_data",
                "component_version": "1.0.0",
                "config": {"entries": [{"key": "greeting", "template": "hi {{ message }}"}]},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lga.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "sd", "input": "input"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "sd", "output": "data"},
                "target": {"node": "end", "input": "json"},
            },
        ],
    }


async def test_mcp_structured_output(server: str) -> None:
    """A Json terminal is returned as MCP structuredContent, plus text (SPEC §8.1)."""
    await _publish(server, _json_flow("mcp-json"))
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{server}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("make_json", {"input_text": "world"})
            assert result.structuredContent == {"greeting": "hi world"}
            assert any(getattr(c, "type", "") == "text" for c in result.content)


async def test_mcp_tool_input_schema_from_start(server: str) -> None:
    """The `data` argument is typed from io.start.input_schema (SPEC §8.1)."""
    spec = hello_spec("mcp-typed")
    spec["flow"]["a2a"] = {"enabled": False}  # MCP mode: serving is exclusive (A2A off)
    spec["flow"]["mcp"] = {"enabled": True, "description": "typed"}
    spec["nodes"][0]["config"]["input_schema"] = {
        "type": "object",
        "properties": {"ticket_id": {"type": "string"}},
        "required": ["ticket_id"],
    }
    await _publish(server, spec)
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{server}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool = next(t for t in tools.tools if t.name == "mcp_typed")
            data_schema = tool.inputSchema["properties"]["data"]
            assert "ticket_id" in data_schema.get("properties", {})


def test_tool_registry_canary_pins_fastmcp_privates() -> None:
    """_ToolRegistry is the ONE seam on FastMCP's private tool manager; pin the
    attributes it depends on so an `mcp` upgrade fails HERE, not silently in
    rebuild()."""
    from mcp.server.fastmcp import FastMCP

    from lga.mcp.server import _ToolRegistry

    mcp = FastMCP("canary")

    async def probe(input_text: str, data: dict[str, Any] | None = None) -> str:
        return input_text

    mcp.add_tool(probe, name="t1", description="canary tool")
    # the private surface _ToolRegistry reaches into
    manager = mcp._tool_manager
    assert isinstance(manager._tools, dict)
    assert "t1" in manager._tools
    assert isinstance(manager._tools["t1"].parameters, dict)

    registry = _ToolRegistry(mcp)
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    registry.patch_data_schema("t1", schema)
    patched = manager._tools["t1"].parameters["properties"]["data"]
    assert patched["properties"] == {"x": {"type": "string"}}
    assert patched["description"] == "Structured flow input."
    registry.remove("t1")
    assert "t1" not in manager._tools
    registry.remove("t1")  # idempotent


async def test_mcp_runs_labeled_mode_mcp(server: str) -> None:
    """MCP invocations are first-class runs: run rows carry mode='mcp', so the
    Runs UI can distinguish them from REST runs."""
    spec = hello_spec("mcp-mode")
    spec["flow"]["a2a"] = {"enabled": False}  # MCP mode: serving is exclusive (A2A off)
    spec["flow"]["mcp"] = {"enabled": True, "tool_name": "mode_probe", "description": "probe"}
    await _publish(server, spec)
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{server}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("mode_probe", {"input_text": "hi"})
    async with httpx.AsyncClient(base_url=server, timeout=30) as client:
        runs = (await client.get("/api/v1/runs")).json()
    modes = {r["mode"] for r in runs if r["flow_slug"] == "mcp-mode"}
    assert modes == {"mcp"}


async def test_e063_interrupt_flow_rejected_without_policy(client: httpx.AsyncClient) -> None:
    spec = approval_spec("mcp-hitl")
    spec["flow"]["a2a"] = {"enabled": False}  # MCP mode: serving is exclusive (A2A off)
    spec["flow"]["mcp"] = {"enabled": True, "description": "hitl tool"}
    response = await client.post("/api/v1/flows", json={"spec": spec})
    flow_id = response.json()["id"]
    response = await client.post(f"/api/v1/flows/{flow_id}/publish", json={"version": "patch"})
    body = response.json()
    assert not body["published"]
    assert "E063" in [d["code"] for d in body["diagnostics"]]


async def test_auto_resolve_policy_allows_publish_and_run(server: str) -> None:
    spec = approval_spec("mcp-auto")
    spec["flow"]["a2a"] = {"enabled": False}  # MCP mode: serving is exclusive (A2A off)
    spec["flow"]["mcp"] = {
        "enabled": True,
        "description": "auto-approved",
        "auto_resolve_interrupts": "approve",
    }
    await _publish(server, spec)
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{server}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("mcp_auto", {"input_text": "draft"})
            text = "".join(
                cast("TextContent", c).text
                for c in result.content
                if getattr(c, "type", "") == "text"
            )
            assert "draft answer" in text
