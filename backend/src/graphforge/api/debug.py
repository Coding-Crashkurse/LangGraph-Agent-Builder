"""Debug dashboard API: task list/detail, SSE event streams, playground
messages, HITL input and cancel (CLAUDE.md §13/§14.2).

The messages/input endpoints go through a real a2a-sdk client against our own
mounted /serve/a2a/{slug} — one execution path, dogfooding the protocol."""

import logging
from typing import Any
from uuid import uuid4

import httpx
from a2a.client import A2AClientError, ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    DataPart,
    Message,
    Part,
    Role,
    Task,
    TaskIdParams,
    TextPart,
)
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from graphforge.api.deps import BusDep, ManagerDep, SessionmakerDep
from graphforge.db.models import RunRow, TaskEventRow
from graphforge.runtime.events import TaskEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/debug", tags=["debug"])


# -- helpers -------------------------------------------------------------------


def _row_to_event(row: TaskEventRow) -> TaskEvent:
    return TaskEvent(
        id=row.id,
        task_id=row.task_id,
        flow_id=row.flow_id,
        source=row.source,
        type=row.type,
        node=row.node,
        data=row.payload or {},
        ts=row.created_at,
    )


def _run_out(row: RunRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "flow_id": row.flow_id,
        "context_id": row.context_id,
        "source": row.source,
        "state": row.state,
        "input_preview": row.input_preview,
        "error": row.error,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _mounted_card(manager: Any, flow_id: str) -> AgentCard:
    mounted = manager.mounted(flow_id)
    if mounted is None or mounted.card is None:
        raise HTTPException(status_code=409, detail="flow is not published with A2A enabled")
    return mounted.card


class _A2ASelfClient:
    """Thin wrapper: a2a-sdk client talking to our own mounted A2A app."""

    def __init__(self, card: AgentCard, *, streaming: bool) -> None:
        self._httpx = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))
        self.client = ClientFactory(
            ClientConfig(streaming=streaming, httpx_client=self._httpx)
        ).create(card)

    async def send(self, message: Message) -> tuple[Task | None, int]:
        last_task: Task | None = None
        events = 0
        async for item in self.client.send_message(message):
            events += 1
            if isinstance(item, tuple):
                last_task = item[0]
        return last_task, events

    async def cancel(self, task_id: str) -> Task:
        return await self.client.cancel_task(TaskIdParams(id=task_id))

    async def aclose(self) -> None:
        await self._httpx.aclose()


async def _get_run(sessionmaker: Any, task_id: str) -> RunRow:
    async with sessionmaker() as session:
        row = await session.get(RunRow, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    return row


# -- task list / detail ---------------------------------------------------------


@router.get("/flows/{flow_id}/tasks")
async def list_tasks(
    flow_id: str,
    sessionmaker: SessionmakerDep,
    state: str | None = None,
    source: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = select(RunRow).where(RunRow.flow_id == flow_id)
    if state:
        stmt = stmt.where(RunRow.state == state)
    if source:
        stmt = stmt.where(RunRow.source == source)
    stmt = stmt.order_by(RunRow.created_at.desc()).limit(min(limit, 500))
    async with sessionmaker() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return [_run_out(row) for row in rows]


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, sessionmaker: SessionmakerDep, request: Request) -> dict[str, Any]:
    run = await _get_run(sessionmaker, task_id)
    task_dump: dict[str, Any] | None = None
    if run.source == "a2a":
        task_store = request.app.state.task_store
        task = await task_store.get(task_id)
        if task is not None:
            task_dump = task.model_dump(exclude_none=True, by_alias=True)
    return {"run": _run_out(run), "task": task_dump}


# -- SSE streams -----------------------------------------------------------------


def _sse_payload(event: TaskEvent) -> dict[str, Any]:
    return {"id": event.id, "event": "task_event", "data": event.model_dump_json()}


@router.get("/tasks/{task_id}/events")
async def task_events(
    task_id: str, request: Request, bus: BusDep, sessionmaker: SessionmakerDep
) -> EventSourceResponse:
    last_event_id = request.headers.get("last-event-id") or request.query_params.get(
        "last_event_id"
    )

    async def stream():
        async with bus.subscribe_task(task_id) as queue:
            seen: set[str] = set()
            # replay persisted events first (Last-Event-ID supported) ...
            stmt = (
                select(TaskEventRow)
                .where(TaskEventRow.task_id == task_id)
                .order_by(TaskEventRow.id)
            )
            if last_event_id:
                stmt = stmt.where(TaskEventRow.id > last_event_id)
            async with sessionmaker() as session:
                rows = (await session.execute(stmt)).scalars().all()
            for row in rows:
                seen.add(row.id)
                yield _sse_payload(_row_to_event(row))
            # ... then live
            while True:
                event = await queue.get()
                if event.id in seen:
                    continue
                yield _sse_payload(event)

    return EventSourceResponse(stream())


@router.get("/flows/{flow_id}/events")
async def flow_events(flow_id: str, request: Request, bus: BusDep) -> EventSourceResponse:
    async def stream():
        async with bus.subscribe_flow(flow_id) as queue:
            while True:
                event = await queue.get()
                yield _sse_payload(event)

    return EventSourceResponse(stream())


# -- playground / HITL / cancel ----------------------------------------------------


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1)
    context_id: str | None = None
    stream: bool = True


class TaskInputRequest(BaseModel):
    text: str | None = None
    data: dict[str, Any] | None = None


@router.post("/flows/{flow_id}/messages")
async def send_message(
    flow_id: str, body: SendMessageRequest, manager: ManagerDep
) -> dict[str, Any]:
    card = _mounted_card(manager, flow_id)
    message = Message(
        role=Role.user,
        parts=[Part(root=TextPart(text=body.message))],
        message_id=str(uuid4()),
        context_id=body.context_id,
    )
    client = _A2ASelfClient(card, streaming=body.stream)
    try:
        task, events = await client.send(message)
    except A2AClientError as exc:
        raise HTTPException(status_code=502, detail=f"A2A call failed: {exc}") from exc
    finally:
        await client.aclose()
    return {
        "task": task.model_dump(exclude_none=True, by_alias=True) if task else None,
        "events": events,
    }


@router.post("/tasks/{task_id}/input")
async def task_input(
    task_id: str,
    body: TaskInputRequest,
    manager: ManagerDep,
    sessionmaker: SessionmakerDep,
) -> dict[str, Any]:
    if body.text is None and body.data is None:
        raise HTTPException(status_code=422, detail="provide text or data")
    run = await _get_run(sessionmaker, task_id)
    if run.source != "a2a":
        raise HTTPException(status_code=409, detail="only A2A tasks can receive follow-up input")
    card = _mounted_card(manager, run.flow_id)
    parts: list[Part] = []
    if body.data is not None:
        parts.append(Part(root=DataPart(data=body.data)))
    if body.text is not None:
        parts.append(Part(root=TextPart(text=body.text)))
    message = Message(
        role=Role.user,
        parts=parts,
        message_id=str(uuid4()),
        task_id=task_id,
        context_id=run.context_id,
    )
    client = _A2ASelfClient(card, streaming=True)
    try:
        task, events = await client.send(message)
    except A2AClientError as exc:
        raise HTTPException(status_code=502, detail=f"A2A call failed: {exc}") from exc
    finally:
        await client.aclose()
    return {
        "task": task.model_dump(exclude_none=True, by_alias=True) if task else None,
        "events": events,
    }


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str, manager: ManagerDep, sessionmaker: SessionmakerDep, bus: BusDep
) -> dict[str, Any]:
    run = await _get_run(sessionmaker, task_id)
    if run.source == "a2a":
        card = _mounted_card(manager, run.flow_id)
        client = _A2ASelfClient(card, streaming=False)
        try:
            task = await client.cancel(task_id)
        except A2AClientError as exc:
            raise HTTPException(status_code=502, detail=f"A2A call failed: {exc}") from exc
        finally:
            await client.aclose()
        return {"state": task.status.state.value if task else "canceled"}
    canceled = manager.cancel_run(task_id)
    return {"state": "canceled" if canceled else run.state}
