"""Unit tests for langgraph_agent_builder.components.tools.basic_tools.

safe_eval + Calculator (pure); HttpRequest / WebSearch drive an in-repo fake
httpx client and the real SSRF guard (no network).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from langgraph_agent_builder.components.tools.basic_tools import (
    Calculator,
    HttpRequest,
    WebSearch,
    safe_eval,
)
from langgraph_agent_builder.sdk.component import BuildContext, Component, NodeFn
from langgraph_agent_builder.sdk.testing import ComponentTestHarness
from langgraph_agent_builder.services.settings import Settings

# --------------------------------------------------------------------------- safe_eval


def test_safe_eval_arithmetic_precedence() -> None:
    assert safe_eval("(2+3)*4/5") == 4.0


def test_safe_eval_unary_and_pow() -> None:
    assert safe_eval("-2 ** 3") == -8


def test_safe_eval_floordiv_and_mod() -> None:
    assert safe_eval("17 // 5") == 3
    assert safe_eval("17 % 5") == 2


def test_safe_eval_rejects_names() -> None:
    with pytest.raises(ValueError, match="unsupported expression element"):
        safe_eval("a + 1")


def test_safe_eval_rejects_calls() -> None:
    with pytest.raises(ValueError, match="unsupported expression element"):
        safe_eval("__import__('os')")


# --------------------------------------------------------------------------- Calculator


async def test_calculator_integer_result() -> None:
    node = ComponentTestHarness().build(Calculator, config={"expression": "2+3"})
    out = await node()
    assert out["text"] == "5"


async def test_calculator_float_result() -> None:
    node = ComponentTestHarness().build(Calculator, config={"expression": "1/2"})
    out = await node()
    assert out["text"] == "0.5"


async def test_calculator_input_port_overrides_field() -> None:
    node = ComponentTestHarness().build(
        Calculator, config={"expression": "0"}, ports={"expression": "6*7"}
    )
    out = await node()
    assert out["text"] == "42"


async def test_calculator_division_by_zero_is_error_text() -> None:
    node = ComponentTestHarness().build(Calculator, config={"expression": "1/0"})
    out = await node()
    assert out["text"].startswith("error:")


async def test_calculator_syntax_error_is_error_text() -> None:
    node = ComponentTestHarness().build(Calculator, config={"expression": "foo("})
    out = await node()
    assert out["text"].startswith("error:")


# --------------------------------------------------------------------------- fake httpx


class _FakeResponse:
    def __init__(
        self,
        *,
        text: str = "",
        json_data: Any = None,
        status_code: int = 200,
        raise_json: bool = False,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.text = text
        self._json = json_data
        self.status_code = status_code
        self._raise_json = raise_json
        self.headers = headers or {}

    def json(self) -> Any:
        if self._raise_json:
            raise ValueError("no json body")
        return self._json

    def raise_for_status(self) -> _FakeResponse:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "http://fake"),
                response=httpx.Response(self.status_code),
            )
        return self


class _FakeHttpClient:
    def __init__(self, responses: list[_FakeResponse], sink: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self._sink = sink

    def _next(self) -> _FakeResponse:
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]

    async def __aenter__(self) -> _FakeHttpClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: Any = None,
    ) -> _FakeResponse:
        self._sink.append(
            {
                "verb": "request",
                "method": method,
                "url": url,
                "json": json,
                "headers": headers or {},
            }
        )
        return self._next()

    async def post(self, url: str, *, json: Any = None, **_: Any) -> _FakeResponse:
        self._sink.append({"verb": "post", "url": url, "json": json})
        return self._next()

    async def get(self, url: str, *, params: Any = None, **_: Any) -> _FakeResponse:
        self._sink.append({"verb": "get", "url": url, "params": params})
        return self._next()


def _install_fake_httpx(
    monkeypatch: pytest.MonkeyPatch, *responses: _FakeResponse
) -> list[dict[str, Any]]:
    sink: list[dict[str, Any]] = []

    def factory(*_: Any, **__: Any) -> _FakeHttpClient:
        return _FakeHttpClient(list(responses), sink)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return sink


def _build(component: type[Component], config: dict[str, Any], settings: Settings) -> NodeFn:
    ctx = BuildContext(node_id="t", config=dict(config), settings=settings)
    return component().build(ctx)


# --------------------------------------------------------------------------- HttpRequest


async def test_http_request_blocks_loopback(sqlite_settings: Settings) -> None:
    node = _build(HttpRequest, {"url": "http://127.0.0.1/x"}, sqlite_settings)
    out = await node({}, {})
    assert out["text"].startswith("blocked:")
    assert "error" in out["json"]


async def test_http_request_get_returns_json(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sqlite_settings.push_allow_private = True  # skip DNS resolution in the guard
    sink = _install_fake_httpx(monkeypatch, _FakeResponse(text='{"a": 1}', json_data={"a": 1}))
    node = _build(HttpRequest, {"url": "http://svc.local/x", "method": "GET"}, sqlite_settings)
    out = await node({}, {})
    assert out["text"] == '{"a": 1}'
    assert out["json"] == {"a": 1}
    assert sink[0]["method"] == "GET"


async def test_http_request_wraps_non_dict_json(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sqlite_settings.push_allow_private = True
    _install_fake_httpx(monkeypatch, _FakeResponse(text="[1, 2]", json_data=[1, 2]))
    node = _build(HttpRequest, {"url": "http://svc.local/x"}, sqlite_settings)
    out = await node({}, {})
    assert out["json"] == {"value": [1, 2]}


async def test_http_request_non_json_body_reports_status(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sqlite_settings.push_allow_private = True
    _install_fake_httpx(monkeypatch, _FakeResponse(text="plain", status_code=204, raise_json=True))
    node = _build(HttpRequest, {"url": "http://svc.local/x"}, sqlite_settings)
    out = await node({}, {})
    assert out["text"] == "plain"
    assert out["json"] == {"status": 204}


async def test_http_request_post_sends_body(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sqlite_settings.push_allow_private = True
    sink = _install_fake_httpx(monkeypatch, _FakeResponse(text="{}", json_data={}))
    node = _build(
        HttpRequest,
        {"url": "http://svc.local/x", "method": "POST", "body": {"k": 1}},
        sqlite_settings,
    )
    await node({}, {})
    assert sink[0]["method"] == "POST"
    assert sink[0]["json"] == {"k": 1}


def _fake_public_dns(monkeypatch: pytest.MonkeyPatch, *public_hosts: str) -> None:
    """getaddrinfo stub: listed hosts resolve public; everything else is real."""
    import socket

    real = socket.getaddrinfo

    def fake(host: str, port: Any, *args: Any, **kwargs: Any) -> Any:
        if host in public_hosts:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)


async def test_http_request_redirect_to_private_is_blocked(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a public URL 302-ing into a private address must fail the per-hop guard
    _fake_public_dns(monkeypatch, "public.example")
    sink = _install_fake_httpx(
        monkeypatch,
        _FakeResponse(status_code=302, headers={"location": "http://127.0.0.1:8010/api"}),
        _FakeResponse(text="never", json_data={}),
    )
    node = _build(HttpRequest, {"url": "http://public.example/x"}, sqlite_settings)
    out = await node({}, {})
    assert out["text"].startswith("blocked:")
    assert len(sink) == 1  # the private hop was never fetched


async def test_http_request_follows_validated_public_redirect(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_public_dns(monkeypatch, "public.example", "cdn.example")
    sink = _install_fake_httpx(
        monkeypatch,
        _FakeResponse(status_code=302, headers={"location": "http://cdn.example/y"}),
        _FakeResponse(text='{"ok": true}', json_data={"ok": True}),
    )
    node = _build(HttpRequest, {"url": "http://public.example/x"}, sqlite_settings)
    out = await node({}, {})
    assert out["json"] == {"ok": True}
    assert [s["url"] for s in sink] == ["http://public.example/x", "http://cdn.example/y"]


# ---------------------------------------------------- idempotency key (§7)
async def test_http_request_injects_idempotency_key(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run's RunContext stamps Idempotency-Key: {run_id}:{node_id}:{iteration}."""
    from langgraph_agent_builder.sdk.runtime import RUN_CTX_KEY, RunContext

    sqlite_settings.push_allow_private = True
    sink = _install_fake_httpx(monkeypatch, _FakeResponse(text="{}", json_data={}))
    node = _build(HttpRequest, {"url": "http://svc.local/x"}, sqlite_settings)
    ctx = RunContext(run_id="run-1", thread_id="th", mode="api")
    await node({}, {"configurable": {RUN_CTX_KEY: ctx}})
    assert sink[0]["headers"]["Idempotency-Key"] == "run-1:t:1"


async def test_http_request_idempotency_opt_out(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from langgraph_agent_builder.sdk.runtime import RUN_CTX_KEY, RunContext

    sqlite_settings.push_allow_private = True
    sink = _install_fake_httpx(monkeypatch, _FakeResponse(text="{}", json_data={}))
    node = _build(HttpRequest, {"url": "http://svc.local/x", "idempotency": False}, sqlite_settings)
    ctx = RunContext(run_id="run-1", thread_id="th")
    await node({}, {"configurable": {RUN_CTX_KEY: ctx}})
    assert "Idempotency-Key" not in sink[0]["headers"]


async def test_http_request_no_idempotency_key_without_run_context(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # agent-tool path passes an empty config (no RunContext) → no header stamped
    sqlite_settings.push_allow_private = True
    sink = _install_fake_httpx(monkeypatch, _FakeResponse(text="{}", json_data={}))
    node = _build(HttpRequest, {"url": "http://svc.local/x"}, sqlite_settings)
    await node({}, {})
    assert "Idempotency-Key" not in sink[0]["headers"]


# --------------------------------------------------------------------------- WebSearch


async def test_web_search_tavily_maps_results(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_httpx(
        monkeypatch,
        _FakeResponse(json_data={"results": [{"title": "T", "url": "U", "content": "C"}]}),
    )
    node = _build(WebSearch, {"provider": "tavily", "query": "q", "api_key": "k"}, sqlite_settings)
    out = await node({}, {})
    assert out["table"] == [{"title": "T", "url": "U", "content": "C"}]


async def test_web_search_serpapi_maps_results(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_httpx(
        monkeypatch,
        _FakeResponse(json_data={"organic_results": [{"title": "T", "link": "L", "snippet": "S"}]}),
    )
    node = _build(WebSearch, {"provider": "serpapi", "query": "q", "api_key": "k"}, sqlite_settings)
    out = await node({}, {})
    assert out["table"] == [{"title": "T", "url": "L", "content": "S"}]


async def test_web_search_missing_api_key_is_error_row(sqlite_settings: Settings) -> None:
    node = _build(WebSearch, {"provider": "tavily", "query": "q"}, sqlite_settings)
    out = await node({}, {})
    assert "api_key is required" in out["table"][0]["error"]


async def test_web_search_http_error_is_error_row(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_httpx(monkeypatch, _FakeResponse(status_code=401, json_data={}))
    node = _build(WebSearch, {"provider": "tavily", "query": "q", "api_key": "k"}, sqlite_settings)
    out = await node({}, {})
    assert out["table"] == [{"error": "tavily search failed: HTTP 401"}]


async def test_web_search_non_json_body_is_error_row(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_httpx(monkeypatch, _FakeResponse(text="<html>", raise_json=True))
    node = _build(WebSearch, {"provider": "serpapi", "query": "q", "api_key": "k"}, sqlite_settings)
    out = await node({}, {})
    assert out["table"] == [{"error": "serpapi returned a non-JSON response"}]


def test_web_search_descriptor_marks_api_key_required_per_provider() -> None:
    for provider, required in (("tavily", True), ("serpapi", True), ("searxng", False)):
        desc = WebSearch.descriptor({"provider": provider})
        field = next(f for f in desc["fields"] if f["name"] == "api_key")
        assert field["required"] is required


async def test_web_search_unknown_provider_returns_empty_table(
    sqlite_settings: Settings,
) -> None:
    node = _build(WebSearch, {"provider": "bogus", "query": "q"}, sqlite_settings)
    out = await node({}, {})
    assert out["table"] == []


async def test_web_search_searxng_blocks_loopback(sqlite_settings: Settings) -> None:
    node = _build(
        WebSearch,
        {"provider": "searxng", "query": "q", "searxng_url": "http://127.0.0.1:8080"},
        sqlite_settings,
    )
    out = await node({}, {})
    assert "error" in out["table"][0]


async def test_web_search_searxng_success(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sqlite_settings.push_allow_private = True
    _install_fake_httpx(
        monkeypatch,
        _FakeResponse(json_data={"results": [{"title": "T", "url": "U", "content": "C"}]}),
    )
    node = _build(
        WebSearch,
        {"provider": "searxng", "query": "q", "searxng_url": "http://searx.local"},
        sqlite_settings,
    )
    out = await node({}, {})
    assert out["table"] == [{"title": "T", "url": "U", "content": "C"}]
