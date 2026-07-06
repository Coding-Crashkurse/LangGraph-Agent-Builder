"""A2A compliance suite (SPEC §15.3) — this suite is the definition of "A2A erfüllt".

Runs against the real app (ASGI) using the official a2a-sdk types for card
validation and raw JSON-RPC for precise wire-level assertions.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
import pytest

from tests.conftest import approval_spec, create_and_publish, hello_spec, slow_spec


def rpc_body(method: str, params: dict[str, Any], id: Any = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params}


def user_message(text: str, **extra: Any) -> dict[str, Any]:
    return {
        "role": "user",
        "messageId": str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": text}],
        **extra,
    }


async def send(
    client: httpx.AsyncClient, slug: str, method: str, params: dict, id: Any = 1
) -> dict[str, Any]:
    response = await client.post(f"/a2a/{slug}/", json=rpc_body(method, params, id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["jsonrpc"] == "2.0" and body["id"] == id
    return body


# ------------------------------------------------------------------ agent card
async def test_card_served_on_both_paths_and_validates(client, svc):
    await create_and_publish(client, hello_spec("card-flow"))
    for path in ("agent-card.json", "agent.json"):
        response = await client.get(f"/a2a/card-flow/.well-known/{path}")
        assert response.status_code == 200
        from a2a.types import AgentCard

        card = AgentCard.model_validate(response.json())
        assert card.capabilities.streaming is True
        assert card.capabilities.push_notifications is True
        assert card.capabilities.state_transition_history is True
        assert card.url.endswith("/a2a/card-flow/")
        assert card.skills[0].id == "card-flow"
        assert card.skills[0].description == "Scripted greeting."
    # GET on the agent root also returns the card
    response = await client.get("/a2a/card-flow/")
    assert response.status_code == 200 and response.json()["name"]


async def test_card_version_bumps_on_republish(client):
    flow_id = await create_and_publish(client, hello_spec("bump-flow"))
    card1 = (await client.get("/a2a/bump-flow/.well-known/agent-card.json")).json()
    response = await client.post(f"/api/v1/flows/{flow_id}/publish", json={"version": "major"})
    assert response.json()["published"]
    card2 = (await client.get("/a2a/bump-flow/.well-known/agent-card.json")).json()
    assert card1["version"] != card2["version"]


# ------------------------------------------------------------------ message/send
async def test_message_send_completes_with_artifact(client):
    await create_and_publish(client, hello_spec("send-flow"))
    body = await send(client, "send-flow", "message/send", {"message": user_message("hi")})
    task = body["result"]
    assert task["status"]["state"] == "completed"
    parts = task["artifacts"][0]["parts"]
    assert {"kind": "text", "text": "Hello from LGA!"} in [
        {"kind": p["kind"], "text": p.get("text")} for p in parts
    ]
    assert task["contextId"]


async def test_multi_turn_context_continuation(client):
    await create_and_publish(client, hello_spec("turns-flow"))
    first = (await send(client, "turns-flow", "message/send", {"message": user_message("one")}))[
        "result"
    ]
    ctx = first["contextId"]
    second = (
        await send(
            client, "turns-flow", "message/send", {"message": user_message("two", contextId=ctx)}
        )
    )["result"]
    assert second["contextId"] == ctx
    assert second["id"] != first["id"]  # new task, same thread


async def test_message_id_dedup(client):
    """Same messageId + taskId ⇒ prior result, don't re-run (SPEC §7.5).

    Exercised on a non-terminal (input-required) task; for terminal tasks the
    terminal-restart error (§7.6) takes precedence.
    """
    await create_and_publish(client, approval_spec("dedup-flow"))
    task = (await send(client, "dedup-flow", "message/send", {"message": user_message("draft")}))[
        "result"
    ]
    assert task["status"]["state"] == "input-required"
    # reject loops back to the fake llm and interrupts again (still non-terminal)
    answer = {
        "role": "user",
        "messageId": str(uuid.uuid4()),
        "taskId": task["id"],
        "contextId": task["contextId"],
        "parts": [{"kind": "data", "data": {"decision": "reject"}}],
    }
    second = (await send(client, "dedup-flow", "message/send", {"message": answer}))["result"]
    assert second["status"]["state"] == "input-required"
    history_len = len(second.get("history") or [])
    # resend the SAME messageId ⇒ prior result, no second resume happens
    third = (await send(client, "dedup-flow", "message/send", {"message": answer}))["result"]
    assert third["status"]["state"] == "input-required"
    assert third["id"] == task["id"]
    # the fake llm did NOT produce another turn (history only grew by the dupe
    # echo + the sdk's recorded status message, never by new agent output)
    assert len(third.get("history") or []) <= history_len + 2


async def test_terminal_task_cannot_restart(client):
    await create_and_publish(client, hello_spec("term-flow"))
    task = (await send(client, "term-flow", "message/send", {"message": user_message("hi")}))[
        "result"
    ]
    retry = user_message("again", taskId=task["id"], contextId=task["contextId"])
    body = await send(client, "term-flow", "message/send", {"message": retry})
    assert "error" in body
    assert "terminal" in body["error"]["message"].lower() or body["error"]["code"] < 0


# ------------------------------------------------------------------ streaming
async def test_message_stream_sse_framing(client):
    """Each SSE data: field is one complete JSON-RPC Response; final flag set."""
    await create_and_publish(client, hello_spec("stream-flow"))
    events: list[dict] = []
    async with client.stream(
        "POST",
        "/a2a/stream-flow/",
        json=rpc_body("message/stream", {"message": user_message("hi")}),
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                assert payload["jsonrpc"] == "2.0"  # complete JSON-RPC response
                events.append(payload["result"])
    kinds = [e.get("kind") for e in events]
    assert "task" in kinds  # initial Task snapshot
    finals = [e for e in events if e.get("final")]
    assert finals, "stream must end with a final=true event"
    states = [e.get("status", {}).get("state") for e in events if e.get("kind") == "status-update"]
    assert "completed" in states
    artifact_events = [e for e in events if e.get("kind") == "artifact-update"]
    assert artifact_events, "artifact must be streamed"


async def test_stream_tokens_artifact_chunks(client):
    spec = hello_spec("tokens-flow")
    spec["nodes"][1]["config"]["stream_tokens"] = True
    await create_and_publish(client, spec)
    chunks: list[dict] = []
    async with client.stream(
        "POST",
        "/a2a/tokens-flow/",
        json=rpc_body("message/stream", {"message": user_message("hi")}),
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                result = json.loads(line[5:].strip()).get("result", {})
                if result.get("kind") == "artifact-update":
                    chunks.append(result)
    streamed = [c for c in chunks if c["artifact"]["artifactId"] == "response-stream"]
    assert streamed and any(c.get("lastChunk") for c in streamed)
    text = "".join(p.get("text", "") for c in streamed for p in c["artifact"]["parts"])
    assert text == "Hello from LGA!"


# ------------------------------------------------------------------ input-required (§7.7)
async def test_input_required_roundtrip_approval(client):
    await create_and_publish(client, approval_spec("hitl-flow"))
    task = (
        await send(client, "hitl-flow", "message/send", {"message": user_message("please draft")})
    )["result"]
    assert task["status"]["state"] == "input-required"
    status_message = task["status"]["message"]
    text_parts = [p for p in status_message["parts"] if p["kind"] == "text"]
    data_parts = [p for p in status_message["parts"] if p["kind"] == "data"]
    assert text_parts[0]["text"] == "Release this answer?"
    assert data_parts[0]["data"]["kind"] == "approval"
    assert data_parts[0]["data"]["options"] == ["approve", "reject"]

    # answer with a DataPart {decision}
    answer = {
        "role": "user",
        "messageId": str(uuid.uuid4()),
        "taskId": task["id"],
        "contextId": task["contextId"],
        "parts": [{"kind": "data", "data": {"decision": "approve"}}],
    }
    done = (await send(client, "hitl-flow", "message/send", {"message": answer}))["result"]
    assert done["status"]["state"] == "completed"
    assert done["id"] == task["id"]  # same task resumed
    text = done["artifacts"][0]["parts"][0]["text"]
    assert text == "draft answer"


async def test_input_required_text_answer_parsed_case_insensitively(client):
    await create_and_publish(client, approval_spec("hitl-text"))
    task = (await send(client, "hitl-text", "message/send", {"message": user_message("draft")}))[
        "result"
    ]
    answer = user_message("APPROVE", taskId=task["id"], contextId=task["contextId"])
    done = (await send(client, "hitl-text", "message/send", {"message": answer}))["result"]
    assert done["status"]["state"] == "completed"


async def test_unparseable_answer_stays_input_required(client):
    await create_and_publish(client, approval_spec("hitl-bad"))
    task = (await send(client, "hitl-bad", "message/send", {"message": user_message("draft")}))[
        "result"
    ]
    answer = user_message("banana", taskId=task["id"], contextId=task["contextId"])
    still = (await send(client, "hitl-bad", "message/send", {"message": answer}))["result"]
    assert still["status"]["state"] == "input-required"
    hint = next(p["text"] for p in still["status"]["message"]["parts"] if p["kind"] == "text")
    assert "approve" in hint.lower() and "reject" in hint.lower()


async def test_stream_closes_final_on_input_required(client):
    await create_and_publish(client, approval_spec("hitl-stream"))
    finals = []
    async with client.stream(
        "POST",
        "/a2a/hitl-stream/",
        json=rpc_body("message/stream", {"message": user_message("draft")}),
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                result = json.loads(line[5:].strip()).get("result", {})
                if result.get("final"):
                    finals.append(result)
    assert finals and finals[-1]["status"]["state"] == "input-required"


# ------------------------------------------------------------------ tasks/*
async def test_tasks_get_history_length(client):
    await create_and_publish(client, hello_spec("hist-flow"))
    task = (await send(client, "hist-flow", "message/send", {"message": user_message("hi")}))[
        "result"
    ]
    body = await send(client, "hist-flow", "tasks/get", {"id": task["id"], "historyLength": 0})
    assert body["result"]["status"]["state"] == "completed"
    body2 = await send(client, "hist-flow", "tasks/get", {"id": task["id"]})
    assert body2["result"].get("history")


async def test_tasks_get_unknown_is_32001(client):
    await create_and_publish(client, hello_spec("t404-flow"))
    body = await send(client, "t404-flow", "tasks/get", {"id": "nope-task"})
    assert body["error"]["code"] == -32001


async def test_cancel_running_and_not_cancelable_terminal(client):
    await create_and_publish(client, slow_spec("cancel-flow", seconds=20))
    task = (
        await send(
            client,
            "cancel-flow",
            "message/send",
            {"message": user_message("zzz"), "configuration": {"blocking": False}},
        )
    )["result"]
    assert task["status"]["state"] in ("submitted", "working")
    await asyncio.sleep(0.4)
    cancelled = (await send(client, "cancel-flow", "tasks/cancel", {"id": task["id"]}))["result"]
    assert cancelled["status"]["state"] == "canceled"
    # canceling a terminal task → -32002 TaskNotCancelable
    body = await send(client, "cancel-flow", "tasks/cancel", {"id": task["id"]})
    assert body["error"]["code"] == -32002


async def test_resubscribe_replays_live_task(client):
    await create_and_publish(client, slow_spec("resub-flow", seconds=2))
    task = (
        await send(
            client,
            "resub-flow",
            "message/send",
            {"message": user_message("zzz"), "configuration": {"blocking": False}},
        )
    )["result"]
    got_final = False
    async with client.stream(
        "POST",
        "/a2a/resub-flow/",
        json=rpc_body("tasks/resubscribe", {"id": task["id"]}),
        timeout=30.0,
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                result = json.loads(line[5:].strip()).get("result", {})
                if result.get("final") or (result.get("status", {}).get("state") == "completed"):
                    got_final = True
                    break
    assert got_final


async def test_resubscribe_unknown_task(client):
    await create_and_publish(client, hello_spec("resub404"))
    async with client.stream(
        "POST",
        "/a2a/resub404/",
        json=rpc_body("tasks/resubscribe", {"id": "missing"}),
    ) as response:
        text = "".join([chunk async for chunk in response.aiter_text()])
    assert "-32001" in text or "TaskNotFound" in text or '"code"' in text


# ------------------------------------------------------------------ push notification config
async def test_push_config_crud(client):
    await create_and_publish(client, hello_spec("push-flow"))
    task = (await send(client, "push-flow", "message/send", {"message": user_message("hi")}))[
        "result"
    ]
    config = {
        "taskId": task["id"],
        "pushNotificationConfig": {
            "id": "cfg1",
            "url": "https://example.com/hook",
            "token": "tok",
        },
    }
    set_body = await send(client, "push-flow", "tasks/pushNotificationConfig/set", config)
    assert "result" in set_body, set_body
    got = await send(client, "push-flow", "tasks/pushNotificationConfig/get", {"id": task["id"]})
    assert got["result"]["pushNotificationConfig"]["url"] == "https://example.com/hook"
    listed = await send(
        client, "push-flow", "tasks/pushNotificationConfig/list", {"id": task["id"]}
    )
    assert len(listed["result"]) == 1
    deleted = await send(
        client,
        "push-flow",
        "tasks/pushNotificationConfig/delete",
        {"id": task["id"], "pushNotificationConfigId": "cfg1"},
    )
    assert "error" not in deleted
    listed2 = await send(
        client, "push-flow", "tasks/pushNotificationConfig/list", {"id": task["id"]}
    )
    assert listed2["result"] == []


async def test_push_config_ssrf_rejected(client):
    await create_and_publish(client, hello_spec("ssrf-flow"))
    task = (await send(client, "ssrf-flow", "message/send", {"message": user_message("hi")}))[
        "result"
    ]
    body = await send(
        client,
        "ssrf-flow",
        "tasks/pushNotificationConfig/set",
        {
            "taskId": task["id"],
            "pushNotificationConfig": {"id": "evil", "url": "http://127.0.0.1:9/steal"},
        },
    )
    assert "error" in body


# ------------------------------------------------------------------ JSON-RPC errors
async def test_unknown_method_32601(client):
    await create_and_publish(client, hello_spec("err-flow"))
    body = await send(client, "err-flow", "totally/bogus", {})
    assert body["error"]["code"] == -32601


async def test_parse_error_32700(client):
    await create_and_publish(client, hello_spec("parse-flow"))
    response = await client.post(
        "/a2a/parse-flow/",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    body = response.json()
    assert body["error"]["code"] == -32700


async def test_invalid_params_32602(client):
    await create_and_publish(client, hello_spec("params-flow"))
    body = await send(client, "params-flow", "message/send", {"nope": True})
    assert body["error"]["code"] in (-32602, -32600)


async def test_unknown_agent_404(client):
    response = await client.post("/a2a/ghost/", json=rpc_body("message/send", {}))
    assert response.status_code == 404


# ------------------------------------------------------------------ auth (§7.11)
async def test_api_key_auth_401_and_success(client, svc):
    spec = hello_spec("auth-flow")
    spec["flow"]["a2a"]["auth"] = "api-key"
    await create_and_publish(client, spec)

    # card stays public for discovery
    card = await client.get("/a2a/auth-flow/.well-known/agent-card.json")
    assert card.status_code == 200
    assert card.json().get("securitySchemes")

    # RPC without key → HTTP-layer 401 with WWW-Authenticate
    response = await client.post(
        "/a2a/auth-flow/", json=rpc_body("message/send", {"message": user_message("hi")})
    )
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers

    # key without the a2a:invoke scope → still 401
    wrong_key, _ = await svc.apikeys.create(["mcp:invoke"], "wrong")
    response = await client.post(
        "/a2a/auth-flow/",
        json=rpc_body("message/send", {"message": user_message("hi")}),
        headers={"X-API-Key": wrong_key},
    )
    assert response.status_code == 401

    key, _ = await svc.apikeys.create(["a2a:invoke"], "right")
    response = await client.post(
        "/a2a/auth-flow/",
        json=rpc_body("message/send", {"message": user_message("hi")}),
        headers={"X-API-Key": key},
    )
    assert response.status_code == 200
    assert response.json()["result"]["status"]["state"] == "completed"


async def test_public_context_namespacing(client, svc):
    """Anonymous callers must not be able to address foreign sessions (§7.11)."""
    await create_and_publish(client, hello_spec("ns-flow"))
    task = (await send(client, "ns-flow", "message/send", {"message": user_message("hi")}))[
        "result"
    ]
    # same client scope (same IP in tests) CAN read it
    body = await send(client, "ns-flow", "tasks/get", {"id": task["id"]})
    assert "result" in body
    # a different client scope behaves as if the task does not exist
    from lga.a2a.scope import current_client_scope

    token = current_client_scope.set("key:someoneelse")
    try:
        from lga.a2a.tasks import DbTaskStore

        store = DbTaskStore(svc.sessions, "ns-flow")
        assert await store.get(task["id"]) is None
    finally:
        current_client_scope.reset(token)


# ------------------------------------------------------------------ task store state machine
async def test_state_transition_history_persisted(client, svc):
    await create_and_publish(client, approval_spec("trans-flow"))
    task = (await send(client, "trans-flow", "message/send", {"message": user_message("draft")}))[
        "result"
    ]
    from lga.a2a.tasks import DbTaskStore

    store = DbTaskStore(svc.sessions, "trans-flow")
    transitions = await store.transitions(task["id"])
    states = [t["to"] for t in transitions]
    assert states[0] == "submitted"
    assert "working" in states and "input-required" in states


async def test_illegal_transition_raises(svc):
    from a2a.types import Message as A2AMessage
    from a2a.types import Part, Role, Task, TaskState, TaskStatus, TextPart

    from lga.a2a.tasks import DbTaskStore, IllegalTaskTransitionError

    store = DbTaskStore(svc.sessions, "x-flow")
    task = Task(
        id="tt1",
        context_id="cc1",
        status=TaskStatus(state=TaskState.completed),
        history=[
            A2AMessage(role=Role.user, message_id="m1", parts=[Part(root=TextPart(text="x"))])
        ],
    )
    await store.save(task)
    task.status = TaskStatus(state=TaskState.working)
    with pytest.raises(IllegalTaskTransitionError):
        await store.save(task)
