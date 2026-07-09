"""Runs / threads / playground REST API (SPEC §9.3, §6.3): blocking + background
+ SSE runs, run listing/detail/delete/cancel, HITL resume, thread state/history,
and the 404/409/422 error branches."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.conftest import approval_spec, create_and_publish, hello_spec, slow_spec

if TYPE_CHECKING:
    import httpx


async def _drain_until_terminal(response: httpx.Response) -> list[str]:
    """Collect SSE event names, stopping at the terminal run event."""
    events: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("event:"):
            name = line[len("event:") :].strip()
            events.append(name)
            if name in ("run_finished", "run_cancelled"):
                break
    return events


# ------------------------------------------------------------- blocking run
async def test_blocking_run_completes_and_is_listed(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("blk"))
    resp = await client.post("/api/v1/flows/blk/run", json={"input_text": "hi"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert "Hello from LGA!" in body["result_text"]
    run_id = body["run_id"]

    listed = await client.get("/api/v1/runs")
    assert listed.status_code == 200
    assert any(r["run_id"] == run_id for r in listed.json())

    detail = await client.get(f"/api/v1/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["flow_slug"] == "blk"


async def test_list_runs_filtered_by_flow_id(client: httpx.AsyncClient) -> None:
    flow_id = await create_and_publish(client, hello_spec("filt"))
    await client.post("/api/v1/flows/filt/run", json={"input_text": "hi"})
    resp = await client.get("/api/v1/runs", params={"flow_id": flow_id})
    assert resp.status_code == 200
    runs = resp.json()
    assert runs
    assert all(r["flow_id"] == flow_id for r in runs)


async def test_run_unknown_flow_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/flows/nope/run", json={"input_text": "hi"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "flow not found"


async def test_run_unrunnable_flow_is_422_with_diagnostics(client: httpx.AsyncClient) -> None:
    spec = {
        "schema_version": "1",
        "flow": {"name": "brk", "slug": "brk"},
        "nodes": [
            {"id": "start", "component_id": "lga.io.start", "config": {}},
            {"id": "ghost", "component_id": "lga.does.not.exist", "config": {}},
        ],
        "edges": [],
    }
    assert (await client.post("/api/v1/flows", json={"spec": spec})).status_code == 201
    resp = await client.post("/api/v1/flows/brk/run", json={"input_text": "hi"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["diagnostics"]
    assert isinstance(detail["message"], str)


async def test_run_with_unknown_file_is_422(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("filerun"))
    resp = await client.post(
        "/api/v1/flows/filerun/run", json={"input_text": "hi", "files": ["missing-file"]}
    )
    assert resp.status_code == 422
    assert "unknown file_id" in resp.json()["detail"]


async def test_run_with_valid_uploaded_file(client: httpx.AsyncClient) -> None:
    # a real upload id resolves through _resolve_files and the run completes
    upload = await client.post(
        "/api/v1/files", files={"file": ("notes.txt", b"hello files", "text/plain")}
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["file_id"]

    await create_and_publish(client, hello_spec("withfile"))
    resp = await client.post(
        "/api/v1/flows/withfile/run", json={"input_text": "hi", "files": [file_id]}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


async def test_run_honours_header_var_override(client: httpx.AsyncClient) -> None:
    # X-LGA-VAR-* headers are harvested; a runnable flow still completes with them set.
    await create_and_publish(client, hello_spec("hdr"))
    resp = await client.post(
        "/api/v1/flows/hdr/run",
        json={"input_text": "hi"},
        headers={"X-LGA-VAR-TENANT": "acme"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


# --------------------------------------------------------- background + SSE
async def test_background_run_returns_202(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("bg"))
    resp = await client.post("/api/v1/flows/bg/run", json={"input_text": "hi", "background": True})
    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"]
    assert body["thread_id"]
    # the run row exists and is pollable
    detail = await client.get(f"/api/v1/runs/{body['run_id']}")
    assert detail.status_code == 200


async def test_streaming_run_emits_terminal_event(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("strm"))
    async with client.stream(
        "POST", "/api/v1/flows/strm/run", json={"input_text": "hi", "stream": True}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = await _drain_until_terminal(response)
    assert "run_finished" in events


async def test_run_events_stream_endpoint(client: httpx.AsyncClient) -> None:
    # start a still-running (briefly sleeping) run in the background, then tail its
    # events — run_finished arrives live and closes the SSE stream.
    await create_and_publish(client, slow_spec("evt", seconds=1.0))
    started = (
        await client.post("/api/v1/flows/evt/run", json={"input_text": "hi", "background": True})
    ).json()
    run_id = started["run_id"]
    async with client.stream("GET", f"/api/v1/runs/{run_id}/events") as response:
        assert response.status_code == 200
        events = await _drain_until_terminal(response)
    assert "run_finished" in events


async def test_run_events_unknown_run_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/runs/does-not-exist/events")
    assert resp.status_code == 404


# ------------------------------------------------------------------ detail 404
async def test_get_unknown_run_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/runs/nope")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "run not found"


# --------------------------------------------------------------- delete / clear
async def test_delete_finished_run_then_404(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("del"))
    run_id = (await client.post("/api/v1/flows/del/run", json={"input_text": "hi"})).json()[
        "run_id"
    ]
    deleted = await client.delete(f"/api/v1/runs/{run_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/runs/{run_id}")).status_code == 404


async def test_delete_unknown_run_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.delete("/api/v1/runs/ghost")).status_code == 404


async def test_delete_active_run_is_409(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, slow_spec("slowdel", seconds=10.0))
    started = (
        await client.post(
            "/api/v1/flows/slowdel/run", json={"input_text": "hi", "background": True}
        )
    ).json()
    run_id = started["run_id"]
    resp = await client.delete(f"/api/v1/runs/{run_id}")
    assert resp.status_code == 409
    assert "cancel it first" in resp.json()["detail"]
    await client.post(f"/api/v1/runs/{run_id}/cancel")  # tidy up the live task


async def test_delete_finished_runs_bulk(client: httpx.AsyncClient) -> None:
    flow_id = await create_and_publish(client, hello_spec("bulk"))
    await client.post("/api/v1/flows/bulk/run", json={"input_text": "hi"})
    resp = await client.delete("/api/v1/runs", params={"flow_id": flow_id})
    assert resp.status_code == 200
    assert resp.json()["deleted"] >= 1


# ------------------------------------------------------------------- cancel
async def test_cancel_running_flow(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, slow_spec("slowcancel", seconds=10.0))
    run_id = (
        await client.post(
            "/api/v1/flows/slowcancel/run", json={"input_text": "hi", "background": True}
        )
    ).json()["run_id"]
    resp = await client.post(f"/api/v1/runs/{run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True


async def test_cancel_unknown_run_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/v1/runs/ghost/cancel")).status_code == 404


# -------------------------------------------------------------------- resume
async def test_hitl_resume_roundtrip(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, approval_spec("appr"))
    started = await client.post("/api/v1/flows/appr/run", json={"input_text": "draft it"})
    assert started.status_code == 200
    body = started.json()
    assert body["status"] == "input_required"
    run_id = body["run_id"]

    resumed = await client.post(
        f"/api/v1/runs/{run_id}/resume", json={"payload": {"decision": "approve"}}
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"


async def test_resume_unknown_run_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/runs/ghost/resume", json={"payload": {}})
    assert resp.status_code == 404


async def test_resume_non_interrupted_run_is_409(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("done"))
    run_id = (await client.post("/api/v1/flows/done/run", json={"input_text": "hi"})).json()[
        "run_id"
    ]
    resp = await client.post(f"/api/v1/runs/{run_id}/resume", json={"payload": {}})
    assert resp.status_code == 409
    assert "not input_required" in resp.json()["detail"]


# -------------------------------------------------------------------- threads
async def test_thread_listing_and_state(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("thr"))
    started = (
        await client.post(
            "/api/v1/flows/thr/run", json={"input_text": "hi", "session_id": "sess-thr"}
        )
    ).json()
    thread_id = started["thread_id"]
    assert thread_id == "sess-thr"

    threads = await client.get("/api/v1/threads", params={"flow_slug": "thr"})
    assert threads.status_code == 200
    assert any(t["thread_id"] == thread_id for t in threads.json())

    state = await client.get(f"/api/v1/threads/{thread_id}/state")
    assert state.status_code == 200
    assert "messages" in state.json()["values"]

    history = await client.get(f"/api/v1/threads/{thread_id}/history")
    assert history.status_code == 200
    assert isinstance(history.json(), list)


async def test_update_thread_state(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("upd"))
    thread_id = (
        await client.post(
            "/api/v1/flows/upd/run", json={"input_text": "hi", "session_id": "sess-upd"}
        )
    ).json()["thread_id"]
    resp = await client.post(
        f"/api/v1/threads/{thread_id}/state", json={"values": {"data": {"marker": "edited"}}}
    )
    assert resp.status_code == 200
    payload: dict[str, Any] = resp.json()
    assert payload["values"]["data"]["marker"] == "edited"  # merged into the data channel


async def test_thread_state_unknown_thread_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/threads/no-such-thread/state")
    assert resp.status_code == 404


async def test_delete_thread(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, hello_spec("delthr"))
    thread_id = (
        await client.post(
            "/api/v1/flows/delthr/run", json={"input_text": "hi", "session_id": "sess-del"}
        )
    ).json()["thread_id"]
    resp = await client.delete(f"/api/v1/threads/{thread_id}")
    assert resp.status_code == 204
