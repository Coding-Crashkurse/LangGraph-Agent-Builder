"""Postgres/SQLite TaskStore + explicit task state machine (SPEC §7.6)."""

from __future__ import annotations

import logging
from typing import Any

from a2a.server.context import ServerCallContext
from a2a.server.tasks import TaskStore
from a2a.types import Task, TaskState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lga.db.models import A2ATaskRow, TaskTransitionRow

logger = logging.getLogger("lga.a2a.tasks")

TERMINAL_STATES = {
    TaskState.completed,
    TaskState.failed,
    TaskState.canceled,
    TaskState.rejected,
}

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


class IllegalTaskTransitionError(RuntimeError):
    pass


def resolve_task_store(setting: str, *, sessions, flow_slug: str, settings=None) -> TaskStore:
    """Pluggable task manager (env `LGA_A2A_TASK_STORE`):

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
            f"invalid LGA_A2A_TASK_STORE {setting!r} — expected db | memory | module:factory"
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

    @staticmethod
    def _scope(context: ServerCallContext | None) -> str:
        if context is not None and context.state:
            value = context.state.get("lga_client_scope")
            if value:
                return str(value)
        from lga.a2a.scope import current_client_scope

        return current_client_scope.get()

    async def save(self, task: Task, context: ServerCallContext | None = None) -> None:
        new_state = (
            task.status.state.value
            if hasattr(task.status.state, "value")
            else str(task.status.state)
        )
        async with self._sessions() as session:
            row = await session.get(A2ATaskRow, task.id)
            if row is None:
                row = A2ATaskRow(
                    id=task.id,
                    context_id=task.context_id or "",
                    flow_slug=self._flow_slug,
                    state=new_state,
                    task=task.model_dump(mode="json", exclude_none=True),
                    client_scope=self._scope(context),
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
                row.task = task.model_dump(mode="json", exclude_none=True)
            await session.commit()

    async def get(self, task_id: str, context: ServerCallContext | None = None) -> Task | None:
        async with self._sessions() as session:
            row = await session.get(A2ATaskRow, task_id)
        if row is None:
            return None
        scope = self._scope(context)
        if row.client_scope and scope and row.client_scope != scope:
            # foreign session (public-agent namespacing, §7.11): behave as unknown
            return None
        return Task.model_validate(row.task)

    async def delete(self, task_id: str, context: ServerCallContext | None = None) -> None:
        async with self._sessions() as session:
            row = await session.get(A2ATaskRow, task_id)
            if row is not None:
                await session.delete(row)
                await session.commit()

    # ---------------------------------------------------------------- extras
    async def transitions(self, task_id: str) -> list[dict[str, Any]]:
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

    async def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
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
