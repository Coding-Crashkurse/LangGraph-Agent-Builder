"""Calculator (safe AST) + HTTP Request tools (SPEC §12.5)."""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any

from langgraph_agent_builder.sdk import BuildContext, Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeConfig, NodeFn

_OPS: dict[type[ast.AST], Callable[..., float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_eval(expression: str) -> float:
    """Arithmetic-only AST evaluation — no names, no calls, no eval (SPEC §10.5)."""

    def _eval(node: ast.AST) -> float:
        match node:
            case ast.Expression(body=body):
                return _eval(body)
            case ast.Constant(value=value) if isinstance(value, (int, float)):
                return value
            case ast.BinOp(left=left, op=op, right=right) if type(op) in _OPS:
                return _OPS[type(op)](_eval(left), _eval(right))
            case ast.UnaryOp(op=op, operand=operand) if type(op) in _OPS:
                return _OPS[type(op)](_eval(operand))
            case _:
                raise ValueError(f"unsupported expression element: {ast.dump(node)[:80]}")

    return _eval(ast.parse(expression.strip(), mode="eval"))


class Calculator(Component):
    component_id = "lab.tools.calculator"
    legacy = True
    display_name = "Calculator"
    description = "Evaluate an arithmetic expression (safe AST — demo tool)."
    icon = "calculator"
    category = "tools"
    tool_mode_supported = True
    tool_mode_default = True  # pure tools: the toolset port is the point

    inputs = [
        fields.StrInput(
            name="expression",
            display_name="Expression",
            info="e.g. (2+3)*4/5",
            tool_mode=True,
            required=True,
        ),
    ]
    outputs = [Output(name="text", display_name="Result", port=ports.TEXT)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            expression = str(
                ctx.get_input(state, "expression") or ctx.get_field("expression") or "0"
            )
            try:
                result = safe_eval(expression)
            except Exception as exc:
                return {"text": f"error: {exc}"}
            return {"text": str(int(result) if float(result).is_integer() else result)}

        return node


_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5


class HttpRequest(Component):
    component_id = "lab.tools.http_request"
    display_name = "HTTP Request"
    description = "GET/POST a URL (SSRF-guarded). Usable as an agent tool."
    icon = "globe"
    category = "tools"
    tool_mode_supported = True
    tool_mode_default = True  # pure tools: the toolset port is the point

    inputs = [
        fields.StrInput(name="url", display_name="URL", required=True, tool_mode=True),
        fields.TabInput(
            name="method", display_name="Method", options=["GET", "POST"], default="GET"
        ),
        fields.NestedDictInput(
            name="body", display_name="Body (JSON)", advanced=True, tool_mode=True
        ),
        fields.DictInput(name="headers", display_name="Headers", advanced=True),
        fields.FloatInput(
            name="timeout_s", display_name="Timeout (s)", default=15.0, advanced=True
        ),
    ]
    outputs = [
        Output(name="text", display_name="Text", port=ports.TEXT),
        Output(name="json", display_name="Json", port=ports.JSON),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        settings = ctx.settings

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            import httpx

            from langgraph_agent_builder.a2a.push import SsrfError, validate_webhook_url
            from langgraph_agent_builder.services.settings import Settings

            guard_settings = settings or Settings()
            url = str(ctx.get_input(state, "url") or ctx.get_field("url") or "")
            try:
                validate_webhook_url(url, guard_settings)
            except SsrfError as exc:
                return {"text": f"blocked: {exc}", "json": {"error": str(exc)}}
            method = str(ctx.get_field("method") or "GET").upper()
            body = ctx.get_field("body") if method == "POST" else None
            headers = dict(ctx.get_field("headers") or {})
            # Redirects are followed manually so EVERY hop passes the SSRF
            # guard — follow_redirects=True would let a public URL 302 into
            # 169.254.169.254 or the local Studio API.
            async with httpx.AsyncClient(
                timeout=float(ctx.get_field("timeout_s") or 15.0), follow_redirects=False
            ) as client:
                for _ in range(_MAX_REDIRECTS + 1):
                    response = await client.request(method, url, json=body, headers=headers)
                    if response.status_code not in _REDIRECT_CODES:
                        break
                    location = response.headers.get("location", "")
                    if not location:
                        break
                    url = str(httpx.URL(url).join(location))
                    try:
                        validate_webhook_url(url, guard_settings)
                    except SsrfError as exc:
                        return {"text": f"blocked: {exc}", "json": {"error": str(exc)}}
                    if response.status_code == 303 or method == "POST":
                        method, body = "GET", None  # matches browser/httpx semantics
            text = response.text[:20000]
            try:
                payload = response.json()
                json_out = payload if isinstance(payload, dict) else {"value": payload}
            except ValueError:
                json_out = {"status": response.status_code}
            return {"text": text, "json": json_out}

        return node


class WebSearch(Component):
    component_id = "lab.tools.web_search"
    legacy = True
    display_name = "Web Search"
    description = "Provider-agnostic web search → Table (SSRF-guarded searxng)."
    icon = "search"
    category = "tools"
    beta = True
    tool_mode_supported = True
    tool_mode_default = True

    inputs = [
        fields.DropdownInput(
            name="provider",
            display_name="Provider",
            options=["tavily", "serpapi", "searxng"],
            default="tavily",
            real_time_refresh=True,  # toggles the api_key required flag
        ),
        fields.QueryInput(name="query", display_name="Query", required=True),
        fields.IntInput(name="max_results", display_name="Max Results", default=5, min=1, max=20),
        fields.SecretInput(
            name="api_key",
            display_name="API Key",
            info="Required for tavily / serpapi; searxng needs none.",
        ),
        fields.StrInput(
            name="searxng_url",
            display_name="SearXNG URL",
            info="Base URL when provider = searxng.",
            advanced=True,
        ),
        fields.FloatInput(
            name="timeout_s", display_name="Timeout (s)", default=20.0, advanced=True
        ),
    ]
    outputs = [Output(name="table", display_name="Results", port=ports.TABLE)]

    @classmethod
    def descriptor(cls, config: NodeConfig | None = None) -> dict[str, Any]:
        """api_key is required for the hosted providers (on_field_change refresh)."""
        desc = super().descriptor(config)
        provider = str((config or {}).get("provider") or "tavily")
        for f in desc["fields"]:
            if f["name"] == "api_key":
                f["required"] = provider in ("tavily", "serpapi")
        return desc

    def build(self, ctx: BuildContext) -> NodeFn:
        settings = ctx.settings

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            import httpx

            provider = str(ctx.get_field("provider") or "tavily")
            query = str(ctx.get_input(state, "query") or ctx.get_field("query") or "")
            k = int(ctx.get_field("max_results") or 5)
            api_key = str(ctx.get_field("api_key") or "")
            if provider in ("tavily", "serpapi") and not api_key:
                return {"table": [{"error": f"api_key is required for provider {provider!r}"}]}
            rows: list[dict[str, Any]] = []
            try:
                async with httpx.AsyncClient(
                    timeout=float(ctx.get_field("timeout_s") or 20.0)
                ) as client:
                    if provider == "tavily":
                        resp = await client.post(
                            "https://api.tavily.com/search",
                            json={"api_key": api_key, "query": query, "max_results": k},
                        )
                        resp.raise_for_status()
                        for r in resp.json().get("results", [])[:k]:
                            rows.append(
                                {
                                    "title": r.get("title"),
                                    "url": r.get("url"),
                                    "content": r.get("content"),
                                }
                            )
                    elif provider == "serpapi":
                        resp = await client.get(
                            "https://serpapi.com/search",
                            params={"q": query, "api_key": api_key, "num": k},
                        )
                        resp.raise_for_status()
                        for r in resp.json().get("organic_results", [])[:k]:
                            rows.append(
                                {
                                    "title": r.get("title"),
                                    "url": r.get("link"),
                                    "content": r.get("snippet"),
                                }
                            )
                    elif provider == "searxng":
                        from langgraph_agent_builder.a2a.push import SsrfError, validate_webhook_url
                        from langgraph_agent_builder.services.settings import Settings

                        base = str(ctx.get_field("searxng_url") or "")
                        try:
                            validate_webhook_url(base, settings or Settings())
                        except SsrfError as exc:
                            return {"table": [{"error": str(exc)}]}
                        resp = await client.get(
                            base.rstrip("/") + "/search",
                            params={"q": query, "format": "json"},
                        )
                        resp.raise_for_status()
                        for r in resp.json().get("results", [])[:k]:
                            rows.append(
                                {
                                    "title": r.get("title"),
                                    "url": r.get("url"),
                                    "content": r.get("content"),
                                }
                            )
            except httpx.HTTPStatusError as exc:
                return {
                    "table": [
                        {"error": f"{provider} search failed: HTTP {exc.response.status_code}"}
                    ]
                }
            except httpx.HTTPError as exc:
                return {"table": [{"error": f"{provider} search failed: {exc}"}]}
            except ValueError:
                return {"table": [{"error": f"{provider} returned a non-JSON response"}]}
            return {"table": rows}

        return node
