"""Runs, threads, playground API (SPEC §9.3) — blocking or SSE."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, cast

import jsonschema  # type: ignore[import-untyped]  # no stubs installed for jsonschema
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from langgraph_agent_builder.api.deps import Services, StudioAuth, header_vars
from langgraph_agent_builder.db.models import RunRow
from langgraph_agent_builder.schema.events import HEARTBEAT_INTERVAL_S
from langgraph_agent_builder.schema.flowspec import end_output_schema, start_input_schema
from langgraph_agent_builder.services.orchestrator import FlowNotRunnableError

if TYPE_CHECKING:
    from langgraph_agent_builder.app import AppServices
    from langgraph_agent_builder.runtime.executor import RunResult

logger = logging.getLogger("langgraph_agent_builder.api.runs")

router = APIRouter(tags=["runs"], dependencies=[StudioAuth])


class RunBody(BaseModel):
    input_text: str = ""
    data: dict[str, Any] | None = None
    files: list[str] = Field(default_factory=list)
    session_id: str | None = None
    tweaks: dict[str, dict[str, Any]] | None = None
    stream: bool = False
    background: bool = False  # 202 + poll (SPEC §6.5)
    until_node: str | None = None  # partial run (SPEC §6.4)
    mode: str = "api"  # playground | api | debug


class ResumeBody(BaseModel):
    payload: Any = None
    debug_action: str | None = None  # step | continue


def run_info(row: RunRow) -> dict[str, Any]:
    return {
        "run_id": row.id,
        "flow_id": row.flow_id,
        "flow_version_id": row.flow_version_id,
        "flow_slug": row.flow_slug,
        "thread_id": row.thread_id,
        "mode": row.mode,
        "status": row.status,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "node_id": row.node_id,
        "result_preview": row.result_preview,
        "started_at": row.started_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


async def _resolve_files(svc: AppServices, file_ids: list[str]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for file_id in file_ids:
        found = await svc.files.get(file_id)
        if found is None:
            raise HTTPException(422, f"unknown file_id {file_id!r}")
        row, _ = found
        files.append({"file_id": row.id, "mime": row.mime, "name": row.name})
    return files


async def _run_event_gen(
    svc: AppServices, run_id: str, after_seq: int, cancel_on_disconnect: bool
) -> AsyncGenerator[dict[str, Any], None]:
    """SSE frames for a run. If the stream is torn down before the run finishes
    and ``cancel_on_disconnect`` is set, request cancellation (SPEC §6.1)."""
    heartbeat = 0.0
    finished = False  # True only when the run reached a terminal event
    agen = svc.bus.subscribe(run_id, after_seq=after_seq).__aiter__()
    try:
        while True:
            try:
                event = await asyncio.wait_for(agen.__anext__(), timeout=HEARTBEAT_INTERVAL_S)
            except TimeoutError:
                heartbeat += 1
                yield {"event": "heartbeat", "data": json.dumps({"n": heartbeat})}
                continue
            except StopAsyncIteration:
                finished = True
                return
            yield event.sse()
    finally:
        # The finally runs on normal completion (finished=True → no-op) and when
        # the client disconnects mid-run (GeneratorExit/CancelledError → cancel).
        # executor.cancel is non-blocking and never awaits, so this is teardown-safe.
        if cancel_on_disconnect and not finished:
            with contextlib.suppress(Exception):
                await svc.executor.cancel(run_id)


def _event_source(svc: AppServices, run_id: str, after_seq: int) -> EventSourceResponse:
    return EventSourceResponse(
        _run_event_gen(svc, run_id, after_seq, bool(svc.settings.cancel_on_disconnect))
    )


def _validate_api_input(run_spec: dict[str, Any], data: dict[str, Any] | None) -> None:
    """§9.3 request contract: structured input must match start.input_schema.
    Text-only calls (data=None) are always valid. An author-side schema defect
    (invalid draft, unresolvable $ref) must never 500 the public endpoint —
    E065 gates it at publish; here we skip validation and log."""
    schema = start_input_schema(run_spec)
    if schema is None or data is None:
        return
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        raise HTTPException(
            422,
            detail={"error": "input does not match the flow's input_schema", "detail": str(exc)},
        ) from exc
    except Exception as exc:
        logger.warning("start.input_schema could not be applied, skipping validation: %s", exc)


def _check_output_contract(run_spec: dict[str, Any], result: RunResult) -> None:
    """§9.3 response contract: a structured result drifting from end.output_schema
    must NOT fail the request — the enforcing guard is publish-time E064/E065;
    the runtime stays permissive and only logs (schema-side failures included)."""
    schema = end_output_schema(run_spec)
    if schema is None or result.result_json is None:
        return
    try:
        jsonschema.validate(result.result_json, schema)
    except jsonschema.ValidationError as exc:
        logger.warning(
            "run %s: structured result does not match the flow's output_schema: %s",
            result.run_id,
            exc.message,
        )
    except Exception as exc:
        logger.warning("run %s: end.output_schema could not be applied: %s", result.run_id, exc)


@router.post("/flows/{id_or_slug}/run")
async def run_flow_endpoint(id_or_slug: str, body: RunBody, request: Request, svc: Services) -> Any:
    # id_or_slug — the slug form is the stable per-flow API base URL (§9)
    flow = await svc.flows.resolve(id_or_slug)
    if flow is None:
        raise HTTPException(404, "flow not found")
    files = await _resolve_files(svc, body.files)
    background = body.stream or body.background
    run_mode = "partial" if body.until_node else body.mode
    run_mode = run_mode if run_mode in ("playground", "api", "debug", "partial") else "api"
    # SPEC §9.3/§7.1: the public API door serves the pinned published version
    # (serve_version); the editable draft only runs the playground/debug/partial
    # paths. Unpublished flows fall back to the draft so first-run-before-publish
    # keeps working. flow_version_id pins resume/thread-state to the same version.
    run_spec: dict[str, Any] = flow.spec
    run_version_id: str | None = None
    if run_mode == "api":
        version = await svc.flows.serve_version(flow)
        if version is not None:
            run_spec = version.flowspec
            run_version_id = version.id
        _validate_api_input(run_spec, body.data)
    try:
        run_id, thread_id, handle_or_result = await svc.orchestrator.start_run(
            spec=run_spec,
            flow_row=flow,
            flow_version_id=run_version_id,
            mode=run_mode,
            input_text=body.input_text,
            data=body.data,
            files=files,
            session_id=body.session_id,
            tweaks=body.tweaks,
            debug=body.mode == "debug",
            background=background,
            until_node=body.until_node,
            extra_vars=header_vars(request),
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
    if body.background:
        from fastapi.responses import JSONResponse

        return JSONResponse({"run_id": run_id, "thread_id": thread_id}, status_code=202)
    # background=False → the orchestrator returns the blocking RunResult
    result = cast("RunResult", handle_or_result)
    _check_output_contract(run_spec, result)
    return {"run_id": run_id, "thread_id": thread_id, **result.model_dump(mode="json")}


@router.get("/runs")
async def list_runs(
    svc: Services,
    flow_id: str | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    return [run_info(r) for r in await svc.runs.list(flow_id=flow_id, limit=limit, offset=offset)]


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


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(run_id: str, svc: Services) -> None:
    """Delete a run trace. Active runs must be cancelled first (409)."""
    row = await svc.runs.get(run_id)
    if row is None:
        raise HTTPException(404, "run not found")
    if row.status in ("pending", "running"):
        raise HTTPException(409, f"run is {row.status} — cancel it first")
    await svc.runs.delete(run_id)


@router.delete("/runs")
async def delete_finished_runs(svc: Services, flow_id: str | None = None) -> dict[str, Any]:
    """Clear all finished run traces (completed/failed/cancelled)."""
    removed = await svc.runs.delete_finished(flow_id=flow_id)
    return {"deleted": removed}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, svc: Services) -> dict[str, Any]:
    if await svc.runs.get(run_id) is None:
        raise HTTPException(404, "run not found")
    cancelled = await svc.executor.cancel(run_id)
    if not cancelled:
        # no live task (e.g. server restarted) — the state rule lives in RunService
        cancelled = await svc.runs.mark_cancelled_if_active(run_id)
    return {"cancelled": cancelled}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, body: ResumeBody, svc: Services) -> dict[str, Any]:
    row = await svc.runs.get(run_id)
    if row is None:
        raise HTTPException(404, "run not found")
    if row.status not in ("input_required",):
        raise HTTPException(409, f"run is {row.status}, not input_required")
    try:
        _, resumed = await svc.orchestrator.resume_run(
            run_id, body.payload, debug_action=body.debug_action, background=False
        )
    except KeyError as exc:
        raise HTTPException(404, "flow for run not found") from exc
    # background=False → the orchestrator returns the blocking RunResult
    result = cast("RunResult", resumed)
    return {"run_id": run_id, **result.model_dump(mode="json")}


# ---------------------------------------------------------------- threads (§6.3)
@router.get("/threads")
async def list_threads(
    svc: Services,
    flow_slug: str | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    threads: list[dict[str, Any]] = await svc.runs.list_threads(
        flow_slug=flow_slug, limit=limit, offset=offset
    )
    return threads


async def _thread_flow_spec(svc: AppServices, thread_id: str) -> dict[str, Any]:
    run = await svc.runs.get_by_thread(thread_id)
    if run is None:
        raise HTTPException(404, "thread not found")
    flow = (
        await svc.flows.get(run.flow_id)
        if run.flow_id
        else await svc.flows.get_by_slug(run.flow_slug)
    )
    if flow is None:
        raise HTTPException(404, "flow for thread not found")
    spec: dict[str, Any] = flow.spec
    return spec


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
