"""Postgres/SQLite TaskStore + explicit task state machine (SPEC §7.6).

a2a-sdk 1.x tasks are protobuf messages; snapshots persist as ProtoJSON
(``MessageToDict``/``ParseDict``) and ``TaskState`` values are plain enum ints.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from a2a.server.context import ServerCallContext
from a2a.server.tasks import TaskStore
from a2a.types import ListTasksRequest, ListTasksResponse, Task, TaskState
from a2a.utils.constants import PROTOCOL_VERSION_1_0
from google.protobuf.json_format import MessageToDict, ParseDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from langgraph_agent_builder.a2a.scope import resolve_client_scope
from langgraph_agent_builder.db.models import A2ATaskRow, TaskTransitionRow
from langgraph_agent_builder.errors import LabRuntimeError
from langgraph_agent_builder.services.settings import Settings

logger = logging.getLogger("langgraph_agent_builder.a2a.tasks")

# explicit transition table — illegal transitions indicate executor bugs
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"working", "canceled", "rejected", "failed", "input-required"},
    "working": {"working", "input-required", "auth-required", "completed", "failed", "canceled"},
    "input-required": {"working", "canceled", "failed", "input-required"},
    "auth-required": {"working", "canceled", "failed"},
    "completed": set(),
    "failed": set(),
    "canceled": set(),
    "rejected": set(),
}


# ``DbTaskStore.list`` (the v1.0 TaskStore ABC method) shadows the builtin
# ``list`` for in-class annotations under ``from __future__ import annotations``;
# alias the row shape at module scope so ``transitions``/``list_tasks`` keep
# their concrete return types.
JsonRows = list[dict[str, Any]]


def state_to_str(state: int) -> str:
    """protobuf ``TASK_STATE_INPUT_REQUIRED`` → the wire/transition name ``input-required``."""
    return str(TaskState.Name(state).removeprefix("TASK_STATE_").lower().replace("_", "-"))


def state_from_str(name: str) -> int:
    """``input-required`` → protobuf ``TaskState.TASK_STATE_INPUT_REQUIRED``."""
    return int(TaskState.Value("TASK_STATE_" + name.upper().replace("-", "_")))


# the §7.6/§7.11 state sets live HERE (protobuf enum ints), derived from the
# transition table so the store's state machine and the executor/handler guards
# cannot drift
TERMINAL_STATES: set[int] = {
    state_from_str(state) for state, targets in ALLOWED_TRANSITIONS.items() if not targets
}
# final-for-a-stream: terminal + the paused states that close an SSE stream (§7.7)
FINAL_STATES: set[int] = TERMINAL_STATES | {
    state_from_str("input-required"),
    state_from_str("auth-required"),
}


class IllegalTaskTransitionError(LabRuntimeError):
    pass


def resolve_task_store(
    setting: str,
    *,
    sessions: async_sessionmaker[AsyncSession],
    flow_slug: str,
    settings: Settings | None = None,
) -> TaskStore:
    """Pluggable task manager (env `LAB_A2A_TASK_STORE`):

    - ``db`` (default): Postgres/SQLite-backed DbTaskStore with transition
      history and public-session scoping
    - ``memory``: a2a-sdk InMemoryTaskStore (no persistence, no scoping)
    - ``"my_pkg.module:factory"``: dotted import path to a callable
      ``factory(sessions=..., flow_slug=..., settings=...) -> TaskStore``
    """
    if setting in ("", "db"):
        return DbTaskStore(sessions, flow_slug)
    if setting == "memory":
        from a2a.server.tasks import InMemoryTaskStore

        return InMemoryTaskStore()
    import importlib

    module_name, _, attr = setting.partition(":")
    if not attr:
        raise ValueError(
            f"invalid LAB_A2A_TASK_STORE {setting!r} — expected db | memory | module:factory"
        )
    factory = getattr(importlib.import_module(module_name), attr)
    store = factory(sessions=sessions, flow_slug=flow_slug, settings=settings)
    if not isinstance(store, TaskStore):
        raise TypeError(f"{setting} did not return an a2a TaskStore (got {type(store)!r})")
    return store


class DbTaskStore(TaskStore):
    """Persists full Task snapshots + transition history; scope-aware (§7.11)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], flow_slug: str) -> None:
        self._sessions = sessions
        self._flow_slug = flow_slug

    async def save(self, task: Task, context: ServerCallContext | None = None) -> None:
        new_state = state_to_str(task.status.state)
        snapshot = MessageToDict(task)
        async with self._sessions() as session:
            row = await session.get(A2ATaskRow, task.id)
            if row is None:
                row = A2ATaskRow(
                    id=task.id,
                    context_id=task.context_id or "",
                    flow_slug=self._flow_slug,
                    state=new_state,
                    task=snapshot,
                    protocol_version=PROTOCOL_VERSION_1_0,
                    client_scope=resolve_client_scope(context),
                )
                session.add(row)
                session.add(TaskTransitionRow(task_id=task.id, from_state="", to_state=new_state))
            else:
                old_state = row.state
                if old_state != new_state:
                    allowed = ALLOWED_TRANSITIONS.get(old_state, set())
                    if new_state not in allowed:
                        logger.error(
                            "illegal task transition %s → %s for %s (executor bug)",
                            old_state,
                            new_state,
                            task.id,
                        )
                        raise IllegalTaskTransitionError(
                            f"illegal transition {old_state} → {new_state}"
                        )
                    session.add(
                        TaskTransitionRow(task_id=task.id, from_state=old_state, to_state=new_state)
                    )
                row.state = new_state
                row.context_id = task.context_id or row.context_id
                row.task = snapshot
            await session.commit()

    async def get(self, task_id: str, context: ServerCallContext | None = None) -> Task | None:
        async with self._sessions() as session:
            row = await session.get(A2ATaskRow, task_id)
        if row is None:
            return None
        scope = resolve_client_scope(context)
        if row.client_scope and scope and row.client_scope != scope:
            # foreign session (public-agent namespacing, §7.11): behave as unknown
            return None
        return cast("Task", ParseDict(row.task, Task(), ignore_unknown_fields=True))

    async def list(
        self, params: ListTasksRequest, context: ServerCallContext | None = None
    ) -> ListTasksResponse:
        """`tasks/list` (§7.6): scope-aware, single-flow, newest-first.

        v1.0 made ``TaskStore.list`` abstract. Filtering honours the same
        public-session scope as :meth:`get`; page_token cursors are not issued
        (single-flow lists stay small), so pagination is a simple size cap.
        """
        scope = resolve_client_scope(context)
        status_filter = state_to_str(params.status) if params.status else None
        async with self._sessions() as session:
            stmt = select(A2ATaskRow).where(A2ATaskRow.flow_slug == self._flow_slug)
            if params.context_id:
                stmt = stmt.where(A2ATaskRow.context_id == params.context_id)
            stmt = stmt.order_by(A2ATaskRow.created_at.desc())
            rows = (await session.execute(stmt)).scalars().all()
        tasks: list[Task] = []
        for row in rows:
            if row.client_scope and scope and row.client_scope != scope:
                continue  # foreign session (public-agent namespacing, §7.11)
            if status_filter is not None and row.state != status_filter:
                continue
            tasks.append(ParseDict(row.task, Task(), ignore_unknown_fields=True))
        page_size = params.page_size or 100
        return ListTasksResponse(
            tasks=tasks[:page_size], total_size=len(tasks), page_size=page_size
        )

    async def delete(self, task_id: str, context: ServerCallContext | None = None) -> None:
        async with self._sessions() as session:
            row = await session.get(A2ATaskRow, task_id)
            if row is not None:
                await session.delete(row)
                await session.commit()

    # ---------------------------------------------------------------- extras
    async def transitions(self, task_id: str) -> JsonRows:
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(TaskTransitionRow)
                        .where(TaskTransitionRow.task_id == task_id)
                        .order_by(TaskTransitionRow.created_at)
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "from": r.from_state,
                "to": r.to_state,
                "ts": r.created_at.isoformat(),
            }
            for r in rows
        ]

    async def list_tasks(self, limit: int = 100) -> JsonRows:
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(A2ATaskRow)
                        .where(A2ATaskRow.flow_slug == self._flow_slug)
                        .order_by(A2ATaskRow.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "task_id": r.id,
                "context_id": r.context_id,
                "state": r.state,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]
