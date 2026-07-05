"""MCP exposure tests: in-memory client session against the per-flow FastMCP."""

from langgraph.checkpoint.memory import InMemorySaver
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent

from graphforge.a2a.executor import RunRegistry
from graphforge.compiler.build import build_flow
from graphforge.mcp_server.server import build_mcp_server
from graphforge.runtime.events import EventBus
from graphforge.runtime.runs import RunLog

from .conftest import hitl_flow, simple_flow


def _make_server(spec, loaded_registry, settings, bus: EventBus):
    spec.publish.mcp = True
    spec.publish.mcp_tool.name = "ask"
    spec.publish.mcp_tool.description = "Ask the flow."
    compiled = build_flow(spec, loaded_registry, settings, InMemorySaver())
    return build_mcp_server(
        spec,
        compiled.graph,
        settings=settings,
        bus=bus,
        run_log=RunLog(None),
        runs=RunRegistry(),
    )


async def test_tool_discovery_and_run(loaded_registry, settings):
    bus = EventBus()
    server = _make_server(simple_flow(slug="mcp-flow"), loaded_registry, settings, bus)
    async with create_connected_server_and_client_session(server._mcp_server) as session:
        tools = await session.list_tools()
        assert [t.name for t in tools.tools] == ["ask"]

        result = await session.call_tool("ask", {"message": "hi"})
        assert not result.isError
        text = next(c.text for c in result.content if isinstance(c, TextContent))
        assert text == "hello from fake"


async def test_thread_id_gives_continuity(loaded_registry, settings):
    bus = EventBus()
    server = _make_server(
        simple_flow(slug="mcp-thread", replies=["one", "two"]), loaded_registry, settings, bus
    )
    async with create_connected_server_and_client_session(server._mcp_server) as session:
        first = await session.call_tool("ask", {"message": "a", "thread_id": "t-1"})
        second = await session.call_tool("ask", {"message": "b", "thread_id": "t-1"})
        texts = []
        for result in (first, second):
            texts.append(next(c.text for c in result.content if isinstance(c, TextContent)))
        assert texts == ["one", "two"]  # same checkpointer thread -> history grew


async def test_interrupt_fails_fast_pointing_to_a2a(loaded_registry, settings):
    bus = EventBus()
    server = _make_server(hitl_flow(slug="mcp-hitl"), loaded_registry, settings, bus)
    async with create_connected_server_and_client_session(server._mcp_server) as session:
        result = await session.call_tool("ask", {"message": "draft"})
        assert result.isError
        text = next(c.text for c in result.content if isinstance(c, TextContent))
        assert "A2A" in text


async def test_agent_card_resource(loaded_registry, settings):
    bus = EventBus()
    server = _make_server(simple_flow(slug="mcp-card"), loaded_registry, settings, bus)
    async with create_connected_server_and_client_session(server._mcp_server) as session:
        resources = await session.list_resources()
        uris = [str(r.uri) for r in resources.resources]
        assert "resource://agent-card" in uris
        content = await session.read_resource("resource://agent-card")
        assert '"name"' in content.contents[0].text
