"""Flows-as-tools MCP server (SPEC §8.1): streamable HTTP + SSE fallback."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

import jsonschema  # type: ignore[import-untyped]  # no stubs installed for jsonschema
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from starlette.responses import JSONResponse

from langgraph_agent_builder.schema.flowspec import end_output_schema, start_input_schema

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from langgraph_agent_builder.app import AppServices
    from langgraph_agent_builder.runtime.executor import RunResult

logger = logging.getLogger("langgraph_agent_builder.mcp.server")


def _validate_structured_result(
    slug: str, structured: dict[str, Any] | None, schema: dict[str, Any]
) -> None:
    """Enforce the flow's declared output contract (SPEC §8.1) as a tool error."""
    if structured is None:
        raise RuntimeError(
            f"flow '{slug}' declares an output_schema but produced no structured result"
        )
    try:
        jsonschema.validate(structured, schema)
    except jsonschema.ValidationError as exc:
        raise RuntimeError(
            f"flow '{slug}' structured result violates its declared output_schema: {exc.message}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"flow '{slug}' declares an output_schema that cannot be applied "
            f"(fix or remove it): {exc}"
        ) from exc


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

    def patch_output_schema(self, name: str, schema: dict[str, Any]) -> None:
        """Declare the tool's `outputSchema` from the flow's end.output_schema (§8.1).

        Assigns only the Tool-level `output_schema` cached property (what
        list_tools serves). Setting `fn_metadata.output_schema` instead would
        make the SDK's convert_result assert on the missing output_model and
        break every call — we validate structured results ourselves.
        """
        tool = self._tools.get(name)
        if tool is not None:
            tool.output_schema = schema


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

            output_schema = end_output_schema(spec_dict)

            def make_tool(
                _spec: dict[str, Any],
                _slug: str,
                _policy: str | None,
                _timeout: float,
                _output_schema: dict[str, Any] | None,
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
                    if _output_schema is not None:
                        _validate_structured_result(_slug, structured, _output_schema)
                    return CallToolResult(
                        content=[TextContent(type="text", text=text)],
                        structuredContent=structured,
                    )

                return run_flow_tool

            self.mcp.add_tool(
                make_tool(spec_dict, slug, policy, timeout, output_schema),
                name=tool_name,
                description=description,
            )
            self._tool_names.add(tool_name)
            start_schema = start_input_schema(spec_dict)
            if start_schema is not None:
                self._registry.patch_data_schema(tool_name, start_schema)
            if output_schema is not None:
                self._registry.patch_output_schema(tool_name, output_schema)
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
