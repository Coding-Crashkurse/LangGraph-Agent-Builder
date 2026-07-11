"""Unit pins for the A2A bridge internals: §7.6 state-set derivation, the §7.9
push decision, the §7.10 machine-readable failure part, and the SSRF pin
(resolve-once/connect-to-validated-address, §10.5).

a2a-sdk 1.x: TaskState values are protobuf enum ints (``TERMINAL_STATES`` etc.
are ``set[int]``), ``TaskStatusUpdateEvent`` has no ``final`` flag, and ``Part``
is flat (``WhichOneof('content')`` → ``text``/``data``/``raw``/``url``)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, Part, Role, Task, TaskState, TaskStatus, TaskStatusUpdateEvent
from google.protobuf.json_format import MessageToDict

from langgraph_agent_builder.a2a.executor import LabAgentExecutor, _A2ASink
from langgraph_agent_builder.a2a.push import (
    DbPushConfigStore,
    GuardedPushSender,
    PinnedWebhook,
    SsrfError,
    resolve_and_pin_webhook,
)
from langgraph_agent_builder.a2a.tasks import (
    ALLOWED_TRANSITIONS,
    FINAL_STATES,
    TERMINAL_STATES,
    state_from_str,
)
from langgraph_agent_builder.runtime.executor import RunResult

if TYPE_CHECKING:
    from langgraph_agent_builder.services.settings import Settings


class _RecordingQueue(EventQueue):
    """Captures enqueued events (the v1.0 EventQueue producer surface is only
    ``enqueue_event``)."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def enqueue_event(self, event: Any) -> None:
        self.events.append(event)


# ------------------------------------------------------------ state sets (§7.6)
def test_terminal_states_derived_from_transition_table() -> None:
    assert TERMINAL_STATES == {
        state_from_str(s) for s in ("completed", "failed", "canceled", "rejected")
    }
    assert FINAL_STATES == TERMINAL_STATES | {
        state_from_str("input-required"),
        state_from_str("auth-required"),
    }
    # every terminal state has an empty transition set and vice versa
    for state, targets in ALLOWED_TRANSITIONS.items():
        assert (state_from_str(state) in TERMINAL_STATES) == (not targets)


# ------------------------------------------------------------ push decision (§7.9)
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("completed", True),
        ("failed", True),
        ("canceled", True),
        ("rejected", True),
        ("input-required", True),
        # v1.0 TaskPushNotificationConfig has no metadata channel, so the old
        # per-config `notify_working` opt-in is gone — working never notifies
        ("working", False),
        ("submitted", False),
        ("auth-required", False),
    ],
)
def test_should_notify_decision(state: str, expected: bool) -> None:
    assert GuardedPushSender._should_notify(state_from_str(state)) is expected


# ------------------------------------------------------------ SSRF pinning (§10.5)
async def test_resolve_and_pin_rejects_non_global_literals(sqlite_settings: Settings) -> None:
    sqlite_settings.push_allow_private = False
    for url in (
        "http://10.0.0.5/hook",
        "http://127.0.0.1:9/hook",
        "http://224.0.0.1/hook",  # multicast — missed by is_private/is_loopback
        "http://0.0.0.0/hook",
        "http://[::ffff:10.0.0.1]/hook",  # IPv6-mapped private form
    ):
        with pytest.raises(SsrfError, match="private address"):
            await resolve_and_pin_webhook(url, sqlite_settings)


async def test_resolve_and_pin_connects_to_validated_address(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pinned target closes the DNS-rebinding TOCTOU: connect to the vetted
    IP, present the original host via Host header and SNI."""
    sqlite_settings.push_allow_private = False

    async def fake_resolve(host: str, port: int | None) -> list[str]:
        assert host == "hook.example"
        return ["93.184.216.34"]

    monkeypatch.setattr("langgraph_agent_builder.a2a.push._resolve", fake_resolve)
    pinned = await resolve_and_pin_webhook("https://hook.example/cb?x=1", sqlite_settings)
    assert pinned == PinnedWebhook(
        url="https://93.184.216.34/cb?x=1",
        host_header="hook.example",
        sni_hostname="hook.example",
    )
    # http keeps the Host pin but needs no SNI
    pinned_http = await resolve_and_pin_webhook("http://hook.example:8080/cb", sqlite_settings)
    assert pinned_http is not None
    assert pinned_http.url == "http://93.184.216.34:8080/cb"
    assert pinned_http.host_header == "hook.example:8080"
    assert pinned_http.sni_hostname is None


async def test_resolve_and_pin_dev_escape_hatch(sqlite_settings: Settings) -> None:
    sqlite_settings.push_allow_private = True
    assert await resolve_and_pin_webhook("http://127.0.0.1:9/hook", sqlite_settings) is None


async def test_delivery_uses_pinned_address(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sqlite_settings.push_allow_private = False

    async def fake_resolve(host: str, port: int | None) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr("langgraph_agent_builder.a2a.push._resolve", fake_resolve)

    class _Cfg:
        url = "https://hook.example/cb"
        token = None

    class _StubStore:
        async def get_info_for_dispatch(self, task_id: str) -> Any:
            return [cast("Any", _Cfg())]

    requests: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    task = Task(
        id="pin1",
        context_id="ctx",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        history=[Message(role=Role.ROLE_USER, message_id="m1", parts=[Part(text="x")])],
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    sender = GuardedPushSender(client, cast("DbPushConfigStore", _StubStore()), sqlite_settings)
    await sender.send_notification("pin1", task)
    await client.aclose()

    assert len(requests) == 1
    assert requests[0].url.host == "93.184.216.34"  # connects to the vetted IP
    assert requests[0].headers["host"] == "hook.example"  # original host preserved


# ------------------------------------------------------------ terminal mapping (§7.10)
async def test_failed_result_carries_machine_readable_rt_code() -> None:
    queue = _RecordingQueue()
    updater = TaskUpdater(queue, "t1", "c1")
    sink = _A2ASink(updater, stream_tokens=False)
    result = RunResult(
        run_id="t1",
        thread_id="th1",
        status="failed",
        error_code="RT002",
        error_message="node exploded",
    )
    await LabAgentExecutor._emit_terminal(result, updater, sink)

    event = next(e for e in queue.events if isinstance(e, TaskStatusUpdateEvent))
    assert event.status.state == TaskState.TASK_STATE_FAILED
    parts = list(event.status.message.parts)
    kinds = {p.WhichOneof("content") for p in parts}
    assert kinds == {"text", "data"}
    data_part = next(p for p in parts if p.WhichOneof("content") == "data")
    assert MessageToDict(data_part.data) == {"run_error_code": "RT002"}  # §7.10
    text_part = next(p for p in parts if p.WhichOneof("content") == "text")
    assert "RT002" in text_part.text
