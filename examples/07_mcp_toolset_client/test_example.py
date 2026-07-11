import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import free_port, load_flow, validate_ok  # noqa: E402

HERE = Path(__file__).parent


def test_validates_clean():
    validate_ok(load_flow(HERE))


def test_toolset_resolves_live_tools():
    """Boot the demo MCP server, resolve the LazyToolset, call a tool."""

    async def _run():
        import importlib.util

        import uvicorn

        spec = importlib.util.spec_from_file_location(
            "demo_mcp_server", HERE / "demo_server.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        port = free_port()
        server = uvicorn.Server(
            uvicorn.Config(
                module.mcp.streamable_http_app(), host="127.0.0.1", port=port,
                log_level="error",
            )
        )
        task = asyncio.get_running_loop().create_task(server.serve())
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)

        try:
            from langgraph_agent_builder.components.tools.mcp_toolset import load_mcp_tools
            from langgraph_agent_builder.runtime.tools import as_langchain_tools

            defs = await load_mcp_tools(
                {"transport": "streamable_http", "url": f"http://127.0.0.1:{port}/mcp"}
            )
            names = sorted(d.name for d in defs)
            assert names == ["lookup_order", "shipping_estimate"]
            tools = as_langchain_tools(defs)
            result = await tools[0].ainvoke({"order_id": "1001"})
            assert "shipped" in str(result)
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=10)

    asyncio.run(_run())
