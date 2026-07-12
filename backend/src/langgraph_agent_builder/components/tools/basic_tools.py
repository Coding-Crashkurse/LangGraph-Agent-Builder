"""HTTP Request tool (SPEC §12.5)."""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.sdk import BuildContext, Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeFn
from langgraph_agent_builder.sdk.runtime import get_run_context

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
        fields.StrInput(
            name="url",
            display_name="URL",
            required=True,
            tool_mode=True,
            expressions=True,
            info="Supports {{ … }} expressions over {input, state, vars}, e.g. "
            "https://api/{{ state.data.id }}.",
        ),
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
        fields.BoolInput(
            name="idempotency",
            display_name="Idempotency Key",
            default=True,
            advanced=True,
            info="Send an Idempotency-Key header ({run_id}:{node_id}:{iteration}) so a "
            "retried run is de-duplicated by the target. Disable for endpoints that "
            "reject unknown headers.",
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
            # Idempotency (REFACTOR.md §7): stamp a per-(run, node, iteration) key
            # so retrying a run doesn't double-execute a side-effecting request.
            # Only on the direct-node path — as an agent tool the RunContext isn't
            # threaded through (runtime/tools.py passes an empty config), so run_id
            # is empty and we skip. A caller-set header always wins (setdefault).
            run_ctx = get_run_context(config)
            if run_ctx.run_id and ctx.get_field("idempotency") is not False:
                iteration = run_ctx.current_iteration(ctx.node_id)
                headers.setdefault("Idempotency-Key", f"{run_ctx.run_id}:{ctx.node_id}:{iteration}")
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
