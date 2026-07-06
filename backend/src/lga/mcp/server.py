"""Flows-as-tools MCP server (SPEC §8.1): streamable HTTP + SSE fallback."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from lga.app import AppServices

logger = logging.getLogger("lga.mcp.server")


class McpManager:
    def __init__(self, svc: AppServices) -> None:
        self._svc = svc
        self.mcp = FastMCP(
            "lga",
            instructions="Published lga flows exposed as tools.",
            streamable_http_path="/",
            sse_path="/sse",
            message_path="/messages/",
            stateless_http=True,
        )
        self._tool_names: set[str] = set()

    # ------------------------------------------------------------ tools
    async def rebuild(self) -> None:
        svc = self._svc
        for name in list(self._tool_names):
            try:
                self.mcp._tool_manager._tools.pop(name, None)  # no public remove in FastMCP
            except Exception:  # pragma: no cover - defensive
                pass
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

            def make_tool(_spec: dict[str, Any], _slug: str, _policy: str | None, _timeout: float):
                async def run_flow_tool(
                    input_text: str,
                    data: dict[str, Any] | None = None,
                    session_id: str | None = None,
                ) -> str:
                    """Run the published flow; returns the terminal text result."""
                    return await self._run(
                        _spec, _slug, input_text, data, session_id, _policy, _timeout
                    )

                return run_flow_tool

            self.mcp.add_tool(
                make_tool(spec_dict, slug, policy, timeout),
                name=tool_name,
                description=description,
            )
            self._tool_names.add(tool_name)
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
    ) -> str:
        svc = self._svc

        async def _execute() -> str:
            run_id, _thread_id, result = await svc.orchestrator.start_run(
                spec=spec,
                flow_row=await svc.flows.get_by_slug(slug),
                mode="api",
                input_text=input_text,
                data={"a2a_input": data} if data else None,
                session_id=session_id,
                background=False,
            )
            hops = 0
            while result.status == "input_required" and policy and hops < 5:
                payload = result.interrupt or {}
                resume: Any = (
                    {"decision": policy}
                    if payload.get("kind") == "approval"
                    else {"text": f"auto-{policy}"}
                )
                _, result = await svc.orchestrator.resume_run(run_id, resume, background=False)
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
            return result.result_text

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

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
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
