"""Resume after a restart keeps event persistence and streaming alive (SPEC §6.2/§6.3).

Simulates a process restart by clearing the bus's in-memory seq counters while
a HITL run is parked in input_required: the resume path must restore the floor
from the persisted events, or every post-resume event collides with
``uq_run_event_seq`` (dropped by the persist loop) and live SSE tails filter
the run's remaining events out as already-replayed.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from tests.conftest import approval_spec, create_and_publish

if TYPE_CHECKING:
    import httpx

    from langgraph_agent_builder.app import AppServices


async def test_resume_after_restart_restores_seq_floor(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    await create_and_publish(client, approval_spec("seq-floor"))
    response = await client.post(
        "/api/v1/flows/seq-floor/run", json={"input_text": "draft", "mode": "api"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "input_required"
    run_id = body["run_id"]

    await svc.bus.drain()
    floor = await svc.runs.max_seq(run_id)
    assert floor > 0

    svc.bus._seq.clear()  # what a process restart does to the in-memory counters

    response = await client.post(
        f"/api/v1/runs/{run_id}/resume", json={"payload": {"decision": "approve"}}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"

    await svc.bus.drain()
    fresh = await svc.runs.load_events(run_id, after_seq=floor)
    names = [e.event for e in fresh]
    assert "run_resumed" in names
    assert "run_finished" in names  # persisted above the old floor, not dropped


def _rpc_send(message: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {"message": message}}


async def test_a2a_resume_after_restart_restores_seq_floor(
    client: httpx.AsyncClient, svc: AppServices
) -> None:
    """Same restart scenario through the A2A bridge (§7.7): its resume path must
    restore the floor before Executor.execute starts publishing again."""
    await create_and_publish(client, approval_spec("a2a-seq-floor"))
    first = await client.post(
        "/a2a/a2a-seq-floor/",
        json=_rpc_send(
            {
                "role": "user",
                "messageId": str(uuid.uuid4()),
                "parts": [{"kind": "text", "text": "draft"}],
            }
        ),
    )
    assert first.status_code == 200, first.text
    task = first.json()["result"]
    assert task["status"]["state"] == "input-required"
    run_id = task["id"]  # one task == one run + its resume chain (§7.6)

    await svc.bus.drain()
    floor = await svc.runs.max_seq(run_id)
    assert floor > 0

    svc.bus._seq.clear()  # what a process restart does to the in-memory counters

    answer = {
        "role": "user",
        "messageId": str(uuid.uuid4()),
        "taskId": task["id"],
        "contextId": task["contextId"],
        "parts": [{"kind": "data", "data": {"decision": "approve"}}],
    }
    done = await client.post("/a2a/a2a-seq-floor/", json=_rpc_send(answer))
    assert done.status_code == 200, done.text
    assert done.json()["result"]["status"]["state"] == "completed"

    await svc.bus.drain()
    fresh = await svc.runs.load_events(run_id, after_seq=floor)
    names = [e.event for e in fresh]
    assert "run_resumed" in names
    assert "run_finished" in names  # persisted above the old floor, not dropped
