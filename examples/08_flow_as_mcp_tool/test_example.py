import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import LiveServer, load_flow, validate_ok  # noqa: E402

HERE = Path(__file__).parent


def test_validates_clean():
    validate_ok(load_flow(HERE))


def test_published_flow_is_an_mcp_tool():
    async def _run():
        async with LiveServer() as server:
            await server.publish(load_flow(HERE))

            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(f"{server.base}/mcp") as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    tool = next(t for t in tools.tools if t.name == "ask_library")
                    assert tool.description == "Ask the library corpus a question."
                    result = await session.call_tool(
                        "ask_library", {"input_text": "who wrote left hand of darkness?"}
                    )
                    text = "".join(
                        c.text for c in result.content if getattr(c, "type", "") == "text"
                    )
                    assert "Le Guin" in text

    asyncio.run(_run())
