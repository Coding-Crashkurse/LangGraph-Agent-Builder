"""Calculator (safe AST) + HTTP Request tools (SPEC §12.5)."""

from __future__ import annotations

import ast
import operator
from typing import Any

from lga.sdk import Component, Output, fields, ports

_OPS = {
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
    component_id = "lga.tools.calculator"
    display_name = "Calculator"
    description = "Evaluate an arithmetic expression (safe AST — demo tool)."
    icon = "calculator"
    category = "tools"
    tool_mode_supported = True

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

    def build(self, ctx):
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


class HttpRequest(Component):
    component_id = "lga.tools.http_request"
    display_name = "HTTP Request"
    description = "GET/POST a URL (SSRF-guarded). Usable as an agent tool."
    icon = "globe"
    category = "tools"
    tool_mode_supported = True

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

    def build(self, ctx):
        settings = ctx.settings

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            import httpx

            from lga.a2a.push import SsrfError, validate_webhook_url
            from lga.services.settings import Settings

            url = str(ctx.get_input(state, "url") or ctx.get_field("url") or "")
            try:
                validate_webhook_url(url, settings or Settings())
            except SsrfError as exc:
                return {"text": f"blocked: {exc}", "json": {"error": str(exc)}}
            method = str(ctx.get_field("method") or "GET").upper()
            async with httpx.AsyncClient(
                timeout=float(ctx.get_field("timeout_s") or 15.0), follow_redirects=True
            ) as client:
                response = await client.request(
                    method,
                    url,
                    json=ctx.get_field("body") if method == "POST" else None,
                    headers=dict(ctx.get_field("headers") or {}),
                )
            text = response.text[:20000]
            try:
                payload = response.json()
                json_out = payload if isinstance(payload, dict) else {"value": payload}
            except ValueError:
                json_out = {"status": response.status_code}
            return {"text": text, "json": json_out}

        return node
