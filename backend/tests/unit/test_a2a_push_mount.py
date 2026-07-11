"""Unit tests for langgraph_agent_builder.a2a.push (SSRF webhook guard + delivery gating) and
langgraph_agent_builder.a2a.mount (ASGI dispatcher error paths + agent registry)."""

from __future__ import annotations

import json
import socket
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from a2a.types import (
    Message,
    Part,
    PushNotificationConfig,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
)

from langgraph_agent_builder.a2a.mount import A2AManager, effective_path
from langgraph_agent_builder.a2a.push import (
    DbPushConfigStore,
    GuardedPushSender,
    SsrfError,
    validate_webhook_url,
)

if TYPE_CHECKING:
    from langgraph_agent_builder.app import AppServices
    from langgraph_agent_builder.services.settings import Settings
    from tests.unit.conftest import SqliteStack


def _task(task_id: str, state: TaskState) -> Task:
    return Task(
        id=task_id,
        context_id="ctx",
        status=TaskStatus(state=state),
        history=[Message(role=Role.user, message_id="m1", parts=[Part(root=TextPart(text="x"))])],
    )


# ============================================================ validate_webhook_url


def test_scheme_must_be_http_or_https(sqlite_settings: Settings) -> None:
    with pytest.raises(SsrfError, match="unsupported scheme"):
        validate_webhook_url("ftp://example.com/hook", sqlite_settings)


def test_prod_requires_https(sqlite_settings: Settings) -> None:
    sqlite_settings.env = "prod"
    sqlite_settings.a2a_allow_http = False
    sqlite_settings.push_allow_private = True  # would otherwise short-circuit
    with pytest.raises(SsrfError, match="https in prod"):
        validate_webhook_url("http://example.com/hook", sqlite_settings)


def test_private_ip_rejected(sqlite_settings: Settings) -> None:
    sqlite_settings.push_allow_private = False
    with pytest.raises(SsrfError, match="private address"):
        validate_webhook_url("http://10.0.0.5/hook", sqlite_settings)


def test_unresolvable_host_rejected(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sqlite_settings.push_allow_private = False

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise socket.gaierror("nope")

    monkeypatch.setattr("langgraph_agent_builder.a2a.push.socket.getaddrinfo", _boom)
    with pytest.raises(SsrfError, match="cannot resolve"):
        validate_webhook_url("http://does-not-exist.example/hook", sqlite_settings)


def test_allow_private_skips_resolution(sqlite_settings: Settings) -> None:
    sqlite_settings.push_allow_private = True
    # loopback would normally be rejected; the flag returns before DNS resolution
    validate_webhook_url("http://127.0.0.1:9/hook", sqlite_settings)


# ============================================================ GuardedPushSender


def _no_call_client() -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    return httpx.AsyncClient(transport=httpx.MockTransport(responder)), calls


async def test_non_notify_state_does_not_deliver(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    settings.push_allow_private = True
    store = DbPushConfigStore(sessions, settings)
    await store.set_info("n1", PushNotificationConfig(id="c", url="http://10.0.0.9/hook"))

    client, calls = _no_call_client()
    sender = GuardedPushSender(client, store, settings)
    await sender.send_notification(_task("n1", TaskState.submitted))  # not a notify state
    assert calls == []
    await client.aclose()


async def test_working_state_without_optin_does_not_deliver(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    settings.push_allow_private = True
    store = DbPushConfigStore(sessions, settings)
    await store.set_info("w1", PushNotificationConfig(id="c", url="http://10.0.0.9/hook"))

    client, calls = _no_call_client()
    sender = GuardedPushSender(client, store, settings)
    await sender.send_notification(_task("w1", TaskState.working))  # no notify_working opt-in
    assert calls == []
    await client.aclose()


async def test_delivery_blocked_when_url_becomes_private(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    settings.push_allow_private = True  # allow storing a private URL
    store = DbPushConfigStore(sessions, settings)
    await store.set_info("b1", PushNotificationConfig(id="c", url="http://10.0.0.9/hook"))

    settings.push_allow_private = False  # now the guard rejects it at send time
    client, calls = _no_call_client()
    sender = GuardedPushSender(client, store, settings)
    await sender.send_notification(_task("b1", TaskState.completed))
    assert calls == []  # SsrfError → logged + skipped, never POSTed
    await client.aclose()


async def test_delivery_gives_up_after_retries(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    settings.push_allow_private = True
    store = DbPushConfigStore(sessions, settings)
    await store.set_info("f1", PushNotificationConfig(id="c", url="http://10.0.0.9/hook"))

    attempts: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    sender = GuardedPushSender(client, store, settings)
    await sender.send_notification(_task("f1", TaskState.completed))
    assert len(attempts) == 3  # RETRIES exhausted, then gives up (logged)
    await client.aclose()


async def test_delete_info_scoped_by_config_id(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    settings.push_allow_private = True
    store = DbPushConfigStore(sessions, settings)
    await store.set_info("d1", PushNotificationConfig(id="cfg-a", url="http://10.0.0.9/a"))
    await store.set_info("d1", PushNotificationConfig(id="cfg-b", url="http://10.0.0.9/b"))

    await store.delete_info("d1", config_id="cfg-a")
    remaining = await store.get_info("d1")
    assert {c.id for c in remaining} == {"cfg-b"}


# ============================================================ mount: effective_path


def test_effective_path_strips_root() -> None:
    assert effective_path({"path": "/agent/rpc", "root_path": "/agent"}) == "/rpc"


def test_effective_path_defaults_to_root() -> None:
    assert effective_path({}) == "/"


# ============================================================ mount: dispatcher

Scope = dict[str, Any]


async def _drive(app: Any, scope: Scope) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent


def _status(sent: list[dict[str, Any]]) -> int:
    start = next(m for m in sent if m["type"] == "http.response.start")
    return int(start["status"])


def _body(sent: list[dict[str, Any]]) -> dict[str, Any]:
    raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return cast("dict[str, Any]", json.loads(raw))


def _manager(settings: Settings) -> A2AManager:
    class _FakeSvc:
        def __init__(self) -> None:
            self.settings = settings

    return A2AManager(cast("AppServices", _FakeSvc()))


async def test_dispatcher_lifespan_scope_is_ignored(sqlite_settings: Settings) -> None:
    manager = _manager(sqlite_settings)
    # a lifespan scope must return without touching receive/send
    await manager({"type": "lifespan"}, None, None)
    await manager.aclose()


async def test_dispatcher_no_agent_selected_is_404(sqlite_settings: Settings) -> None:
    manager = _manager(sqlite_settings)
    scope: Scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    sent = await _drive(manager, scope)
    assert _status(sent) == 404
    assert _body(sent)["detail"] == "no agent selected"
    await manager.aclose()


async def test_dispatcher_unknown_agent_is_404(sqlite_settings: Settings) -> None:
    manager = _manager(sqlite_settings)
    scope: Scope = {"type": "http", "method": "GET", "path": "/ghost", "headers": []}
    sent = await _drive(manager, scope)
    assert _status(sent) == 404
    assert "ghost" in _body(sent)["detail"]
    await manager.aclose()


async def test_dispatcher_rejects_http_in_prod(sqlite_settings: Settings) -> None:
    sqlite_settings.env = "prod"
    sqlite_settings.a2a_allow_http = False
    manager = _manager(sqlite_settings)

    reached = {"v": False}

    async def _agent(_s: Scope, _r: Any, _snd: Any) -> None:
        reached["v"] = True

    manager._apps["x"] = _agent  # a registered agent to get past the lookup

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/x",
        "scheme": "http",
        "headers": [],
    }
    sent = await _drive(manager, scope)
    assert _status(sent) == 403
    assert "https in prod" in _body(sent)["detail"]
    assert reached["v"] is False  # never dispatched to the agent
    await manager.aclose()


async def test_manager_slugs_and_card_json_reflect_registry(sqlite_settings: Settings) -> None:
    manager = _manager(sqlite_settings)
    assert manager.slugs == []
    assert manager.card_json("nope") is None

    async def _agent(_s: Scope, _r: Any, _snd: Any) -> None:
        return None

    manager._apps["b"] = _agent
    manager._apps["a"] = _agent
    manager._cards["a"] = {"name": "Agent A"}
    assert manager.slugs == ["a", "b"]  # sorted
    assert manager.card_json("a") == {"name": "Agent A"}
    await manager.aclose()


# ============================================================ mount: rebuild (app tier)


async def test_rebuild_skips_a2a_disabled_flows(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    from tests.conftest import create_and_publish, hello_spec

    enabled = hello_spec("mounted-on")
    disabled = hello_spec("mounted-off")
    disabled["flow"]["a2a"] = {"enabled": False, "description": "off", "examples": ["x"]}

    await create_and_publish(client, enabled)
    await create_and_publish(client, disabled)
    assert svc.a2a is not None  # mounted by the app lifespan
    await svc.a2a.rebuild()

    assert "mounted-on" in svc.a2a.slugs
    assert "mounted-off" not in svc.a2a.slugs
    assert svc.a2a.card_json("mounted-on") is not None
