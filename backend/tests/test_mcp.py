"""MCP suite (SPEC §15.4): list/call via real mcp client, schema fidelity, E063."""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
import uvicorn

from tests.conftest import approval_spec, hello_spec


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def server(sqlite_settings):
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


async def _publish(base: str, spec: dict) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        response = await client.post("/api/v1/flows", json={"spec": spec})
        assert response.status_code == 201, response.text
        flow_id = response.json()["id"]
        response = await client.post(f"/api/v1/flows/{flow_id}/publish", json={"version": "minor"})
        assert response.json()["published"], response.text


async def test_mcp_list_and_call(server):
    spec = hello_spec("mcp-hello")
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
            text = "".join(c.text for c in result.content if getattr(c, "type", "") == "text")
            assert "Hello from LGA!" in text


async def test_mcp_tool_name_never_uuid(server):
    spec = hello_spec("mcp-slug")
    spec["flow"]["mcp"] = {"enabled": True, "description": "tool"}
    await _publish(server, spec)
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{server}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert any(t.name == "mcp_slug" for t in tools.tools)


async def test_e063_interrupt_flow_rejected_without_policy(client):
    spec = approval_spec("mcp-hitl")
    spec["flow"]["mcp"] = {"enabled": True, "description": "hitl tool"}
    response = await client.post("/api/v1/flows", json={"spec": spec})
    flow_id = response.json()["id"]
    response = await client.post(f"/api/v1/flows/{flow_id}/publish", json={"version": "patch"})
    body = response.json()
    assert not body["published"]
    assert "E063" in [d["code"] for d in body["diagnostics"]]


async def test_auto_resolve_policy_allows_publish_and_run(server):
    spec = approval_spec("mcp-auto")
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
            text = "".join(c.text for c in result.content if getattr(c, "type", "") == "text")
            assert "draft answer" in text
