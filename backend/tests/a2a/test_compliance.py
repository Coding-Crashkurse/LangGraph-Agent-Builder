"""A2A compliance suite (SPEC §15.3) — this suite is the definition of "A2A erfüllt".

Runs against the real app (ASGI) over the a2a-sdk 1.x REST HTTP+JSON transport
(protocol v1.0): ``POST /a2a/{slug}/message:send`` & friends, ProtoJSON bodies,
and google.rpc-shaped error payloads (``{"error": {"code", "status", "message",
"details": [ErrorInfo]}}``, HTTP status == ``code``). Task/message/enum fields
are protobuf ProtoJSON: enums serialize as their full names (``TASK_STATE_*``,
``ROLE_*``) and ``Part`` is flat (``{"text": …}`` / ``{"data": …}``).
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from tests.conftest import approval_spec, create_and_publish, hello_spec, slow_spec

if TYPE_CHECKING:
    from langgraph_agent_builder.app import AppServices


def user_message(text: str, **extra: Any) -> dict[str, Any]:
    return {
        "role": "ROLE_USER",
        "messageId": str(uuid.uuid4()),
        "parts": [{"text": text}],
        **extra,
    }


async def send(
    client: httpx.AsyncClient,
    slug: str,
    message: dict[str, Any],
    *,
    configuration: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """POST message:send; caller inspects status_code + json()."""
    body: dict[str, Any] = {"message": message}
    if configuration is not None:
        body["configuration"] = configuration
    return await client.post(f"/a2a/{slug}/message:send", json=body, headers=headers)


async def send_task(
    client: httpx.AsyncClient,
    slug: str,
    message: dict[str, Any],
    *,
    configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST message:send expecting a Task; returns the Task dict."""
    response = await send(client, slug, message, configuration=configuration)
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json()["task"])


def error_reason(response: httpx.Response) -> str:
    return str(response.json()["error"]["details"][0]["reason"])


# ------------------------------------------------------------------ agent card
async def test_card_served_and_validates(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("card-flow"))
    response = await client.get("/a2a/card-flow/.well-known/agent-card.json")
    assert response.status_code == 200
    card = response.json()
    assert card["capabilities"]["streaming"] is True
    assert card["capabilities"]["pushNotifications"] is True
    assert card["skills"][0]["id"] == "card-flow"
    assert card["skills"][0]["description"] == "Scripted greeting."
    # v1.0 advertises the HTTP+JSON interface under supportedInterfaces[]
    iface = card["supportedInterfaces"][0]
    assert iface["url"].endswith("/a2a/card-flow")
    assert iface["protocolBinding"] == "HTTP+JSON"
    # GET on the agent root also returns the card
    root = await client.get("/a2a/card-flow/")
    assert root.status_code == 200
    assert root.json()["name"]


async def test_authenticated_extended_card_wired(client: httpx.AsyncClient) -> None:
    """GetExtendedAgentCard is a §7.5 MUST; v1 returns the same card."""
    await create_and_publish(client, hello_spec("ext-flow"))
    card = (await client.get("/a2a/ext-flow/.well-known/agent-card.json")).json()
    response = await client.get("/a2a/ext-flow/extendedAgentCard")
    assert response.status_code == 200, response.text
    assert response.json()["name"] == card["name"]


async def test_card_version_bumps_on_republish(client: httpx.AsyncClient) -> None:
    flow_id = await create_and_publish(client, hello_spec("bump-flow"))
    card1 = (await client.get("/a2a/bump-flow/.well-known/agent-card.json")).json()
    response = await client.post(f"/api/v1/flows/{flow_id}/publish", json={"version": "major"})
    assert response.json()["published"]
    card2 = (await client.get("/a2a/bump-flow/.well-known/agent-card.json")).json()
    assert card1["version"] != card2["version"]


# ------------------------------------------------------------------ message/send
async def test_message_send_completes_with_artifact(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("send-flow"))
    task = await send_task(client, "send-flow", user_message("hi"))
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    parts = task["artifacts"][0]["parts"]
    assert any(p.get("text") == "Hello from LAB!" for p in parts)
    assert task["contextId"]


async def test_multi_turn_context_continuation(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("turns-flow"))
    first = await send_task(client, "turns-flow", user_message("one"))
    ctx = first["contextId"]
    second = await send_task(client, "turns-flow", user_message("two", contextId=ctx))
    assert second["contextId"] == ctx
    assert second["id"] != first["id"]  # new task, same thread


async def test_message_id_dedup(client: httpx.AsyncClient) -> None:
    """Same messageId + taskId ⇒ prior result, don't re-run (SPEC §7.5).

    Exercised on a non-terminal (input-required) task; for terminal tasks the
    terminal-restart error (§7.6) takes precedence.
    """
    await create_and_publish(client, approval_spec("dedup-flow"))
    task = await send_task(client, "dedup-flow", user_message("draft"))
    assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    answer = {
        "role": "ROLE_USER",
        "messageId": str(uuid.uuid4()),
        "taskId": task["id"],
        "contextId": task["contextId"],
        "parts": [{"data": {"decision": "reject"}}],
    }
    # reject loops back to the fake llm and interrupts again (still non-terminal)
    second = await send_task(client, "dedup-flow", answer)
    assert second["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    # resend the SAME messageId ⇒ prior result, no second resume happens
    third = await send_task(client, "dedup-flow", answer)
    assert third["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    assert third["id"] == task["id"]


async def test_terminal_task_cannot_restart(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("term-flow"))
    task = await send_task(client, "term-flow", user_message("hi"))
    retry = user_message("again", taskId=task["id"], contextId=task["contextId"])
    response = await send(client, "term-flow", retry)
    assert response.status_code == 400
    assert error_reason(response) in ("INVALID_PARAMS", "TASK_NOT_CANCELABLE")


# ------------------------------------------------------------------ streaming
async def _collect_stream(
    client: httpx.AsyncClient, slug: str, method: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with client.stream(
        "POST", f"/a2a/{slug}/{method}", json=params, timeout=30.0
    ) as response:
        assert response.status_code == 200, await response.aread()
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


async def test_message_stream_sse_framing(client: httpx.AsyncClient) -> None:
    """Each SSE data: field is one StreamResponse; task snapshot first, terminal last."""
    await create_and_publish(client, hello_spec("stream-flow"))
    events = await _collect_stream(
        client, "stream-flow", "message:stream", {"message": user_message("hi")}
    )
    assert any("task" in e for e in events)  # initial Task snapshot
    states = [e["statusUpdate"]["status"]["state"] for e in events if "statusUpdate" in e]
    assert "TASK_STATE_COMPLETED" in states
    assert any("artifactUpdate" in e for e in events), "artifact must be streamed"


async def test_stream_tokens_artifact_chunks(client: httpx.AsyncClient) -> None:
    spec = hello_spec("tokens-flow")
    spec["nodes"][1]["config"]["stream_tokens"] = True
    await create_and_publish(client, spec)
    events = await _collect_stream(
        client, "tokens-flow", "message:stream", {"message": user_message("hi")}
    )
    streamed = [
        e["artifactUpdate"]
        for e in events
        if "artifactUpdate" in e
        and e["artifactUpdate"]["artifact"].get("artifactId") == "response-stream"
    ]
    assert streamed
    assert any(a.get("lastChunk") for a in streamed)
    text = "".join(p.get("text", "") for a in streamed for p in a["artifact"]["parts"])
    assert text == "Hello from LAB!"


# ------------------------------------------------------------------ input-required (§7.7)
async def test_input_required_roundtrip_approval(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, approval_spec("hitl-flow"))
    task = await send_task(client, "hitl-flow", user_message("please draft"))
    assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    parts = task["status"]["message"]["parts"]
    text_parts = [p for p in parts if "text" in p]
    data_parts = [p for p in parts if "data" in p]
    assert text_parts[0]["text"] == "Release this answer?"
    assert data_parts[0]["data"]["kind"] == "approval"
    assert data_parts[0]["data"]["options"] == ["approve", "reject"]

    answer = {
        "role": "ROLE_USER",
        "messageId": str(uuid.uuid4()),
        "taskId": task["id"],
        "contextId": task["contextId"],
        "parts": [{"data": {"decision": "approve"}}],
    }
    done = await send_task(client, "hitl-flow", answer)
    assert done["status"]["state"] == "TASK_STATE_COMPLETED"
    assert done["id"] == task["id"]  # same task resumed
    assert done["artifacts"][0]["parts"][0]["text"] == "draft answer"


async def test_input_required_text_answer_parsed_case_insensitively(
    client: httpx.AsyncClient,
) -> None:
    await create_and_publish(client, approval_spec("hitl-text"))
    task = await send_task(client, "hitl-text", user_message("draft"))
    answer = user_message("APPROVE", taskId=task["id"], contextId=task["contextId"])
    done = await send_task(client, "hitl-text", answer)
    assert done["status"]["state"] == "TASK_STATE_COMPLETED"


async def test_unparseable_answer_stays_input_required(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, approval_spec("hitl-bad"))
    task = await send_task(client, "hitl-bad", user_message("draft"))
    answer = user_message("banana", taskId=task["id"], contextId=task["contextId"])
    still = await send_task(client, "hitl-bad", answer)
    assert still["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    hint = next(p["text"] for p in still["status"]["message"]["parts"] if "text" in p)
    assert "approve" in hint.lower()
    assert "reject" in hint.lower()


async def test_stream_closes_on_input_required(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, approval_spec("hitl-stream"))
    events = await _collect_stream(
        client, "hitl-stream", "message:stream", {"message": user_message("draft")}
    )
    states = [e["statusUpdate"]["status"]["state"] for e in events if "statusUpdate" in e]
    assert states, "expected at least one status update"
    assert states[-1] == "TASK_STATE_INPUT_REQUIRED"


# ------------------------------------------------------------------ tasks/*
async def test_tasks_get_history_length(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("hist-flow"))
    task = await send_task(client, "hist-flow", user_message("hi"))
    trimmed = await client.get(f"/a2a/hist-flow/tasks/{task['id']}", params={"historyLength": 0})
    assert trimmed.status_code == 200
    assert trimmed.json()["status"]["state"] == "TASK_STATE_COMPLETED"
    full = await client.get(f"/a2a/hist-flow/tasks/{task['id']}")
    assert full.json().get("history")


async def test_tasks_get_unknown_is_404(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("t404-flow"))
    response = await client.get("/a2a/t404-flow/tasks/nope-task")
    assert response.status_code == 404
    assert error_reason(response) == "TASK_NOT_FOUND"


async def test_tasks_list_returns_flow_tasks(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("list-flow"))
    task = await send_task(client, "list-flow", user_message("hi"))
    response = await client.get("/a2a/list-flow/tasks")
    assert response.status_code == 200
    ids = {t["id"] for t in response.json().get("tasks", [])}
    assert task["id"] in ids


async def test_cancel_running_task(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, slow_spec("cancel-flow", seconds=20))
    task = await send_task(
        client, "cancel-flow", user_message("zzz"), configuration={"returnImmediately": True}
    )
    assert task["status"]["state"] in ("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING")
    await asyncio.sleep(0.4)
    response = await client.post(f"/a2a/cancel-flow/tasks/{task['id']}:cancel", json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"]["state"] == "TASK_STATE_CANCELED"


async def test_cancel_terminal_task_not_cancelable(client: httpx.AsyncClient) -> None:
    """Canceling a completed (terminal) task ⇒ 400 TASK_NOT_CANCELABLE (§7.6)."""
    await create_and_publish(client, hello_spec("done-flow"))
    task = await send_task(client, "done-flow", user_message("hi"))
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    await asyncio.sleep(0.2)  # let the finished task's ActiveTask leave the registry
    response = await client.post(f"/a2a/done-flow/tasks/{task['id']}:cancel", json={})
    assert response.status_code == 400
    assert error_reason(response) == "TASK_NOT_CANCELABLE"


async def test_resubscribe_replays_live_task(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, slow_spec("resub-flow", seconds=3))
    task = await send_task(
        client, "resub-flow", user_message("zzz"), configuration={"returnImmediately": True}
    )
    got_terminal = False
    async with client.stream(
        "GET", f"/a2a/resub-flow/tasks/{task['id']}:subscribe", timeout=30.0
    ) as response:
        assert response.status_code == 200, await response.aread()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            state = None
            if "task" in event:
                state = event["task"]["status"]["state"]
            elif "statusUpdate" in event:
                state = event["statusUpdate"]["status"]["state"]
            if state == "TASK_STATE_COMPLETED":
                got_terminal = True
                break
    assert got_terminal


async def test_resubscribe_unknown_task(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("resub404"))
    async with client.stream(
        "GET", "/a2a/resub404/tasks/missing:subscribe", timeout=10.0
    ) as response:
        await response.aread()
    assert response.status_code == 404


# ------------------------------------------------------------------ push notification config
async def test_push_config_crud(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("push-flow"))
    task = await send_task(client, "push-flow", user_message("hi"))
    tid = task["id"]
    set_response = await client.post(
        f"/a2a/push-flow/tasks/{tid}/pushNotificationConfigs",
        json={"id": "cfg1", "url": "https://example.com/hook", "token": "tok"},
    )
    assert set_response.status_code == 200, set_response.text
    assert set_response.json()["url"] == "https://example.com/hook"

    got = await client.get(f"/a2a/push-flow/tasks/{tid}/pushNotificationConfigs/cfg1")
    assert got.json()["url"] == "https://example.com/hook"

    listed = await client.get(f"/a2a/push-flow/tasks/{tid}/pushNotificationConfigs")
    assert len(listed.json()["configs"]) == 1

    deleted = await client.delete(f"/a2a/push-flow/tasks/{tid}/pushNotificationConfigs/cfg1")
    assert deleted.status_code == 200
    listed2 = await client.get(f"/a2a/push-flow/tasks/{tid}/pushNotificationConfigs")
    assert listed2.json().get("configs", []) == []


async def test_push_disabled_flow_rejects_and_honest_card(client: httpx.AsyncClient) -> None:
    """§7.9 capability honesty: pushNotifications:false ⇒ card says so and every
    push-config method returns PUSH_NOTIFICATION_NOT_SUPPORTED (§7.10)."""
    spec = hello_spec("push-off")
    spec["flow"]["a2a"]["push_notifications"] = False
    await create_and_publish(client, spec)
    card = (await client.get("/a2a/push-off/.well-known/agent-card.json")).json()
    assert card["capabilities"].get("pushNotifications", False) is False
    task = await send_task(client, "push-off", user_message("hi"))
    tid = task["id"]
    calls = [
        client.post(
            f"/a2a/push-off/tasks/{tid}/pushNotificationConfigs",
            json={"id": "c1", "url": "https://example.com/hook"},
        ),
        client.get(f"/a2a/push-off/tasks/{tid}/pushNotificationConfigs/c1"),
        client.get(f"/a2a/push-off/tasks/{tid}/pushNotificationConfigs"),
        client.delete(f"/a2a/push-off/tasks/{tid}/pushNotificationConfigs/c1"),
    ]
    for coro in calls:
        response = await coro
        assert response.status_code == 400, response.text
        assert error_reason(response) == "PUSH_NOTIFICATION_NOT_SUPPORTED"


async def test_push_config_ssrf_rejected(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("ssrf-flow"))
    task = await send_task(client, "ssrf-flow", user_message("hi"))
    response = await client.post(
        f"/a2a/ssrf-flow/tasks/{task['id']}/pushNotificationConfigs",
        json={"id": "evil", "url": "http://127.0.0.1:9/steal"},
    )
    assert response.status_code >= 400


# ---------------------------------------------------------- content negotiation (§7.8/§7.10)
async def test_accepted_output_modes_mismatch(client: httpx.AsyncClient) -> None:
    """Unsatisfiable acceptedOutputModes ⇒ CONTENT_TYPE_NOT_SUPPORTED (§7.5)."""
    await create_and_publish(client, hello_spec("modes-flow"))
    response = await send(
        client,
        "modes-flow",
        user_message("hi"),
        configuration={"acceptedOutputModes": ["image/png"]},
    )
    assert response.status_code == 400
    assert error_reason(response) == "CONTENT_TYPE_NOT_SUPPORTED"


async def test_file_part_disallowed_mime(client: httpx.AsyncClient) -> None:
    """A file part outside LAB_A2A_ACCEPTED_MIME ⇒ CONTENT_TYPE_NOT_SUPPORTED (§7.8)."""
    await create_and_publish(client, hello_spec("mime-flow"))
    message = {
        "role": "ROLE_USER",
        "messageId": str(uuid.uuid4()),
        "parts": [
            {
                "raw": base64.b64encode(b"MZ...").decode(),
                "mediaType": "application/x-msdownload",
                "filename": "evil.bin",
            }
        ],
    }
    response = await send(client, "mime-flow", message)
    assert response.status_code == 400
    assert error_reason(response) == "CONTENT_TYPE_NOT_SUPPORTED"


async def test_file_part_allowed_mime_accepted(client: httpx.AsyncClient) -> None:
    """A file part matching the allowlist runs normally (§7.8)."""
    await create_and_publish(client, hello_spec("mime-ok-flow"))
    message = {
        "role": "ROLE_USER",
        "messageId": str(uuid.uuid4()),
        "parts": [
            {"text": "hi"},
            {
                "raw": base64.b64encode(b"hello").decode(),
                "mediaType": "text/plain",
                "filename": "note.txt",
            },
        ],
    }
    task = await send_task(client, "mime-ok-flow", message)
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"


async def test_unexpected_exception_sanitized(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7.6/§7.10: unexpected server errors reach the client as generic
    diagnostic text — never str(exc), which routinely embeds DSNs or paths."""
    await create_and_publish(client, hello_spec("boom-flow"))

    from langgraph_agent_builder.runtime.executor import Executor

    async def explode(self: Executor, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("postgres://user:s3cret@10.0.0.7:5432/lab")

    monkeypatch.setattr(Executor, "execute", explode)
    response = await send(client, "boom-flow", user_message("hi"))
    assert response.status_code == 200, response.text
    task = response.json()["task"]
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert task["status"]["message"]["parts"][0]["text"] == "internal error"
    wire = json.dumps(response.json())
    assert "s3cret" not in wire
    assert "postgres://" not in wire


# ------------------------------------------------------------------ transport errors
async def test_invalid_json_body_is_400(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("parse-flow"))
    response = await client.post(
        "/a2a/parse-flow/message:send",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400


async def test_malformed_request_is_400(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("params-flow"))
    response = await client.post("/a2a/params-flow/message:send", json={"nope": True})
    assert response.status_code == 400


async def test_unknown_agent_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/a2a/ghost/message:send", json={"message": user_message("x")})
    assert response.status_code == 404


# ------------------------------------------------------------------ auth (§7.11)
async def test_api_key_auth_401_and_success(client: httpx.AsyncClient, svc: AppServices) -> None:
    spec = hello_spec("auth-flow")
    spec["flow"]["a2a"]["auth"] = "api-key"
    await create_and_publish(client, spec)

    # card stays public for discovery
    card = await client.get("/a2a/auth-flow/.well-known/agent-card.json")
    assert card.status_code == 200
    assert card.json().get("securitySchemes")

    # no key → HTTP-layer 401 with WWW-Authenticate
    response = await send(client, "auth-flow", user_message("hi"))
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers

    # key without the a2a:invoke scope → still 401
    wrong_key, _ = await svc.apikeys.create(["mcp:invoke"], "wrong")
    response = await send(client, "auth-flow", user_message("hi"), headers={"X-API-Key": wrong_key})
    assert response.status_code == 401

    key, _ = await svc.apikeys.create(["a2a:invoke"], "right")
    response = await send(client, "auth-flow", user_message("hi"), headers={"X-API-Key": key})
    assert response.status_code == 200
    assert response.json()["task"]["status"]["state"] == "TASK_STATE_COMPLETED"


async def test_public_context_namespacing(client: httpx.AsyncClient, svc: AppServices) -> None:
    """Anonymous callers must not be able to address foreign sessions (§7.11)."""
    await create_and_publish(client, hello_spec("ns-flow"))
    task = await send_task(client, "ns-flow", user_message("hi"))
    # a different client scope behaves as if the task does not exist
    from langgraph_agent_builder.a2a.scope import current_client_scope
    from langgraph_agent_builder.a2a.tasks import DbTaskStore

    token = current_client_scope.set("key:someoneelse")
    try:
        store = DbTaskStore(svc.sessions, "ns-flow")
        assert await store.get(task["id"]) is None
    finally:
        current_client_scope.reset(token)


# ------------------------------------------------------------------ task store state machine
async def test_state_transition_history_persisted(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    await create_and_publish(client, approval_spec("trans-flow"))
    task = await send_task(client, "trans-flow", user_message("draft"))
    from langgraph_agent_builder.a2a.tasks import DbTaskStore

    store = DbTaskStore(svc.sessions, "trans-flow")
    states = [t["to"] for t in await store.transitions(task["id"])]
    assert states[0] == "submitted"
    assert "working" in states
    assert "input-required" in states


async def test_illegal_transition_raises(svc: AppServices) -> None:
    from a2a.types import Message as A2AMessage
    from a2a.types import Part, Role, Task, TaskState, TaskStatus

    from langgraph_agent_builder.a2a.tasks import DbTaskStore, IllegalTaskTransitionError

    store = DbTaskStore(svc.sessions, "x-flow")
    task = Task(
        id="tt1",
        context_id="cc1",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        history=[A2AMessage(role=Role.ROLE_USER, message_id="m1", parts=[Part(text="x")])],
    )
    await store.save(task)
    task.status.state = TaskState.TASK_STATE_WORKING
    with pytest.raises(IllegalTaskTransitionError):
        await store.save(task)
