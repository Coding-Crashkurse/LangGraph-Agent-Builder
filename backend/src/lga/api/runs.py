"""Runs, threads, playground API (SPEC §9.3) — blocking or SSE."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from lga.api.deps import Services, StudioAuth
from lga.db.models import RunRow
from lga.schema.events import HEARTBEAT_INTERVAL_S
from lga.services.orchestrator import FlowNotRunnableError

router = APIRouter(tags=["runs"], dependencies=[StudioAuth])


class RunBody(BaseModel):
    input_text: str = ""
    data: dict[str, Any] | None = None
    files: list[str] = Field(default_factory=list)
    session_id: str | None = None
    tweaks: dict[str, dict[str, Any]] | None = None
    stream: bool = False
    mode: str = "api"  # playground | api | debug


class ResumeBody(BaseModel):
    payload: Any = None
    debug_action: str | None = None  # step | continue


def run_info(row: RunRow) -> dict[str, Any]:
    return {
        "run_id": row.id,
        "flow_id": row.flow_id,
        "flow_slug": row.flow_slug,
        "thread_id": row.thread_id,
        "mode": row.mode,
        "status": row.status,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "result_preview": row.result_preview,
        "started_at": row.started_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


async def _resolve_files(svc: Any, file_ids: list[str]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for file_id in file_ids:
        found = await svc.files.get(file_id)
        if found is None:
            raise HTTPException(422, f"unknown file_id {file_id!r}")
        row, _ = found
        files.append({"file_id": row.id, "mime": row.mime, "name": row.name})
    return files


def _event_source(svc: Any, run_id: str, after_seq: int) -> EventSourceResponse:
    async def gen():
        heartbeat = 0.0
        agen = svc.bus.subscribe(run_id, after_seq=after_seq).__aiter__()
        while True:
            try:
                event = await asyncio.wait_for(agen.__anext__(), timeout=HEARTBEAT_INTERVAL_S)
            except TimeoutError:
                heartbeat += 1
                yield {"event": "heartbeat", "data": json.dumps({"n": heartbeat})}
                continue
            except StopAsyncIteration:
                return
            yield event.sse()

    return EventSourceResponse(gen())


@router.post("/flows/{flow_ref}/run")
async def run_flow_endpoint(flow_ref: str, body: RunBody, svc: Services) -> Any:
    # flow_ref = id or slug — the slug form is the stable per-flow API base URL
    flow = await svc.flows.get(flow_ref) or await svc.flows.get_by_slug(flow_ref)
    if flow is None:
        raise HTTPException(404, "flow not found")
    files = await _resolve_files(svc, body.files)
    try:
        run_id, thread_id, handle_or_result = await svc.orchestrator.start_run(
            spec=flow.spec,
            flow_row=flow,
            mode=body.mode if body.mode in ("playground", "api", "debug") else "api",
            input_text=body.input_text,
            data=body.data,
            files=files,
            session_id=body.session_id,
            tweaks=body.tweaks,
            debug=body.mode == "debug",
            background=body.stream,
        )
    except FlowNotRunnableError as exc:
        raise HTTPException(
            422,
            detail={
                "message": str(exc),
                "diagnostics": [d.model_dump(mode="json") for d in exc.diagnostics],
            },
        ) from exc
    if body.stream:
        return _event_source(svc, run_id, 0)
    result = handle_or_result
    return {"run_id": run_id, "thread_id": thread_id, **result.model_dump(mode="json")}


@router.get("/runs")
async def list_runs(
    svc: Services, flow_id: str | None = None, limit: int = Query(default=100, le=1000)
) -> list[dict[str, Any]]:
    return [run_info(r) for r in await svc.runs.list(flow_id=flow_id, limit=limit)]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, svc: Services) -> dict[str, Any]:
    row = await svc.runs.get(run_id)
    if row is None:
        raise HTTPException(404, "run not found")
    return run_info(row)


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    svc: Services,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    row = await svc.runs.get(run_id)
    if row is None:
        raise HTTPException(404, "run not found")
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    return _event_source(svc, run_id, after)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, svc: Services) -> dict[str, Any]:
    row = await svc.runs.get(run_id)
    if row is None:
        raise HTTPException(404, "run not found")
    cancelled = await svc.executor.cancel(run_id)
    if not cancelled and row.status in ("pending", "running", "input_required"):
        await svc.runs.update_status(run_id, "cancelled", error_code="RT104")
        cancelled = True
    return {"cancelled": cancelled}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, body: ResumeBody, svc: Services) -> dict[str, Any]:
    row = await svc.runs.get(run_id)
    if row is None:
        raise HTTPException(404, "run not found")
    if row.status not in ("input_required",):
        raise HTTPException(409, f"run is {row.status}, not input_required")
    try:
        _, result = await svc.orchestrator.resume_run(
            run_id, body.payload, debug_action=body.debug_action, background=False
        )
    except KeyError as exc:
        raise HTTPException(404, "flow for run not found") from exc
    return {"run_id": run_id, **result.model_dump(mode="json")}


# ---------------------------------------------------------------- threads (§6.3)
@router.get("/threads")
async def list_threads(svc: Services, flow_slug: str | None = None) -> list[dict[str, Any]]:
    return await svc.runs.list_threads(flow_slug=flow_slug)


async def _thread_flow_spec(svc: Any, thread_id: str) -> dict[str, Any]:
    runs = await svc.runs.list(limit=1000)
    run = next((r for r in runs if r.thread_id == thread_id), None)
    if run is None:
        raise HTTPException(404, "thread not found")
    flow = (
        await svc.flows.get(run.flow_id)
        if run.flow_id
        else await svc.flows.get_by_slug(run.flow_slug)
    )
    if flow is None:
        raise HTTPException(404, "flow for thread not found")
    return flow.spec


def _snapshot_json(snapshot: Any) -> dict[str, Any]:
    values = dict(snapshot.values or {})
    messages = values.pop("messages", [])
    return {
        "next": list(snapshot.next or ()),
        "values": {
            **{k: _jsonable(v) for k, v in values.items()},
            "messages": [
                {"type": getattr(m, "type", "?"), "content": getattr(m, "content", str(m))}
                for m in messages
            ],
        },
        "created_at": getattr(snapshot, "created_at", None),
    }


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {k: _jsonable(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_jsonable(v) for v in value]
        return repr(value)


@router.get("/threads/{thread_id}/state")
async def thread_state(thread_id: str, svc: Services) -> dict[str, Any]:
    spec = await _thread_flow_spec(svc, thread_id)
    snapshot = await svc.orchestrator.thread_state(spec, thread_id)
    return _snapshot_json(snapshot)


@router.post("/threads/{thread_id}/state")
async def update_thread_state(
    thread_id: str, body: dict[str, Any], svc: Services
) -> dict[str, Any]:
    """Debug-mode state editing (SPEC §11.5) — guarded client-side by confirm."""
    spec = await _thread_flow_spec(svc, thread_id)
    await svc.orchestrator.update_thread_state(spec, thread_id, body.get("values") or {})
    snapshot = await svc.orchestrator.thread_state(spec, thread_id)
    return _snapshot_json(snapshot)


@router.get("/threads/{thread_id}/history")
async def thread_history(
    thread_id: str, svc: Services, limit: int = Query(default=50, le=200)
) -> list[dict[str, Any]]:
    spec = await _thread_flow_spec(svc, thread_id)
    history = await svc.orchestrator.thread_history(spec, thread_id, limit=limit)
    return [_snapshot_json(s) for s in history]


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, svc: Services) -> None:
    checkpointer = await svc.checkpointers.get()
    if hasattr(checkpointer, "adelete_thread"):
        await checkpointer.adelete_thread(thread_id)
