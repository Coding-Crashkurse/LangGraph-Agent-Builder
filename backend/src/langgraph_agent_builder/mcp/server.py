"""Flows-as-tools MCP server (SPEC §8.1): streamable HTTP + SSE fallback."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from langgraph_agent_builder.app import AppServices
    from langgraph_agent_builder.runtime.executor import RunResult

logger = logging.getLogger("langgraph_agent_builder.mcp.server")


def _start_input_schema(spec: dict[str, Any]) -> dict[str, Any] | None:
    """The declared structured-input JSON Schema of the flow's `start` node.

    SPEC §8.1: the MCP tool's `data` argument is typed from io.start.input_schema
    so clients see a typed tool instead of an opaque dict.
    """
    for node in spec.get("nodes", []):
        if node.get("component_id") == "lab.io.start":
            schema = (node.get("config") or {}).get("input_schema")
            if isinstance(schema, dict) and schema.get("properties"):
                return schema
    return None


class _ToolRegistry:
    """The ONE seam that touches FastMCP's private tool manager.

    FastMCP has no public remove-tool or patch-schema API, so every private
    access (`_tool_manager._tools`) lives here — an `mcp` upgrade breaks
    exactly this class (canary test in tests/test_mcp.py pins the attributes).
    """

    def __init__(self, mcp: FastMCP) -> None:
        self._mcp = mcp

    @property
    def _tools(self) -> dict[str, Any]:
        return self._mcp._tool_manager._tools

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    def patch_data_schema(self, name: str, schema: dict[str, Any]) -> None:
        """Type the generic `data` arg from the flow's declared input schema (§8.1)."""
        tool = self._tools.get(name)
        if tool is not None and isinstance(tool.parameters, dict):
            props = tool.parameters.setdefault("properties", {})
            props["data"] = {**schema, "description": "Structured flow input."}


class McpManager:
    def __init__(self, svc: AppServices) -> None:
        self._svc = svc
        self.mcp = FastMCP(
            "langgraph-agent-builder",
            instructions="Published LangGraph Agent Builder flows exposed as tools.",
            streamable_http_path="/",
            sse_path="/sse",
            message_path="/messages/",
            stateless_http=True,
        )
        self._registry = _ToolRegistry(self.mcp)
        self._tool_names: set[str] = set()

    # ------------------------------------------------------------ tools
    async def rebuild(self) -> None:
        svc = self._svc
        for name in list(self._tool_names):
            self._registry.remove(name)
        self._tool_names.clear()

        for _flow, version, spec in await svc.flows.published_flows():
            if not spec.flow.mcp.enabled:
                continue
            slug = spec.flow.slug
            tool_name = spec.flow.mcp.tool_name or slug.replace("-", "_")
            description = spec.flow.mcp.description or spec.flow.description or spec.flow.name
            spec_dict = version.flowspec
            policy = spec.flow.mcp.auto_resolve_interrupts
            timeout = spec.flow.mcp.timeout_s or svc.settings.mcp_timeout_s

            def make_tool(
                _spec: dict[str, Any], _slug: str, _policy: str | None, _timeout: float
            ) -> Callable[[str, dict[str, Any] | None, str | None], Coroutine[Any, Any, Any]]:
                async def run_flow_tool(
                    input_text: str,
                    data: dict[str, Any] | None = None,
                    session_id: str | None = None,
                ) -> Any:
                    """Run the published flow.

                    Returns the terminal message as text content plus the
                    Json/Table result as MCP structuredContent when present (§8.1).
                    """
                    text, structured = await self._run(
                        _spec, _slug, input_text, data, session_id, _policy, _timeout
                    )
                    return CallToolResult(
                        content=[TextContent(type="text", text=text)],
                        structuredContent=structured,
                    )

                return run_flow_tool

            self.mcp.add_tool(
                make_tool(spec_dict, slug, policy, timeout),
                name=tool_name,
                description=description,
            )
            self._tool_names.add(tool_name)
            start_schema = _start_input_schema(spec_dict)
            if start_schema is not None:
                self._registry.patch_data_schema(tool_name, start_schema)
        logger.info("MCP tools mounted: %s", ", ".join(sorted(self._tool_names)) or "(none)")

    async def _run(
        self,
        spec: dict[str, Any],
        slug: str,
        input_text: str,
        data: dict[str, Any] | None,
        session_id: str | None,
        policy: str | None,
        timeout_s: float,
    ) -> tuple[str, dict[str, Any] | None]:
        svc = self._svc

        async def _execute() -> tuple[str, dict[str, Any] | None]:
            run_id, _thread_id, started = await svc.orchestrator.start_run(
                spec=spec,
                flow_row=await svc.flows.get_by_slug(slug),
                mode="mcp",  # first-class run mode — distinguishes MCP from REST runs
                input_text=input_text,
                data={"a2a_input": data} if data else None,
                session_id=session_id,
                background=False,
            )
            result = cast("RunResult", started)  # background=False ⇒ RunResult
            hops = 0
            while result.status == "input_required" and policy and hops < 5:
                payload = result.interrupt or {}
                resume: Any = (
                    {"decision": policy}
                    if payload.get("kind") == "approval"
                    else {"text": f"auto-{policy}"}
                )
                _, resumed = await svc.orchestrator.resume_run(run_id, resume, background=False)
                result = cast("RunResult", resumed)
                hops += 1
            if result.status == "input_required":
                raise RuntimeError(
                    "flow paused for human input — MCP has no input-required concept; "
                    "use the A2A endpoint for approval-style flows"
                )
            if result.status != "completed":
                raise RuntimeError(
                    f"run {result.status}: {result.error_code or ''} "
                    f"{result.error_message or ''}".strip()
                )
            return result.result_text, result.result_json

        return await asyncio.wait_for(_execute(), timeout=timeout_s)

    # ------------------------------------------------------------ asgi
    def http_app(self) -> Any:
        return self.mcp.streamable_http_app()

    def sse_app(self) -> Any:
        return self.mcp.sse_app()


class McpAuthMiddleware:
    """X-API-Key with mcp:invoke scope when auth is enabled (SPEC §8.1)."""

    def __init__(self, app: Any, svc: AppServices) -> None:
        self._app = app
        self._svc = svc

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not self._svc.settings.auth_enabled:
            await self._app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        api_key = headers.get("x-api-key", "")
        if not api_key or not await self._svc.apikeys.verify(api_key, "mcp:invoke"):
            response = JSONResponse(
                {"error": "invalid or missing API key (scope mcp:invoke)"},
                status_code=401,
                headers={"WWW-Authenticate": 'ApiKey header="X-API-Key"'},
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)
