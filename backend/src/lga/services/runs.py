"""Run bookkeeping + event persistence glue (SPEC §6.2, §9.3)."""

from __future__ import annotations

import builtins
import contextlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lga.db.models import RunEventRow, RunRow
from lga.schema.events import RunEvent

TERMINAL_STATUSES = ("completed", "failed", "cancelled")
EVENT_TTL_DAYS = 7


class RunService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    # ---------------------------------------------------------------- rows
    async def create(
        self,
        run_id: str,
        *,
        thread_id: str,
        mode: str,
        flow_id: str | None = None,
        flow_version_id: str | None = None,
        flow_slug: str = "",
    ) -> None:
        async with self._sessions() as session:
            session.add(
                RunRow(
                    id=run_id,
                    thread_id=thread_id,
                    mode=mode,
                    flow_id=flow_id,
                    flow_version_id=flow_version_id,
                    flow_slug=flow_slug,
                    status="pending",
                )
            )
            await session.commit()

    def session(self) -> AsyncSession:
        """Open a new session on the shared app-DB sessionmaker.

        Public seam for collaborators (e.g. the orchestrator) that need ad-hoc
        queries on the same database without reaching into ``_sessions``.
        """
        return self._sessions()

    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        result_preview: str | None = None,
        node_id: str | None = None,
        **_: Any,
    ) -> None:
        async with self._sessions() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                return
            row.status = status
            if error_code:
                row.error_code = error_code
            if error_message:
                row.error_message = error_message[:2000]
            if node_id:
                row.node_id = node_id  # failing node (SPEC §5.6)
            if result_preview is not None:
                row.result_preview = result_preview
            if status in TERMINAL_STATUSES:
                row.finished_at = datetime.now(UTC)
            await session.commit()

    async def get(self, run_id: str) -> RunRow | None:
        async with self._sessions() as session:
            return await session.get(RunRow, run_id)

    async def list(
        self, flow_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[RunRow]:
        async with self._sessions() as session:
            stmt = select(RunRow).order_by(RunRow.started_at.desc()).limit(limit).offset(offset)
            if flow_id:
                stmt = stmt.where(RunRow.flow_id == flow_id)
            return list((await session.execute(stmt)).scalars().all())

    async def get_by_thread(self, thread_id: str) -> RunRow | None:
        """Most recent run on a thread (runs.thread_id is indexed)."""
        async with self._sessions() as session:
            return (
                (
                    await session.execute(
                        select(RunRow)
                        .where(RunRow.thread_id == thread_id)
                        .order_by(RunRow.started_at.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )

    async def list_threads(
        self, flow_slug: str | None = None, limit: int = 100, offset: int = 0
    ) -> builtins.list[dict[str, Any]]:
        """Threads aggregated in SQL (SPEC §6.3), newest activity first.

        One window query: rank runs per thread (newest = 1) and count the
        partition, so last_run_at/last_status come from the latest run without
        loading every run row into Python.
        """
        rank = (
            func.row_number()
            .over(partition_by=RunRow.thread_id, order_by=RunRow.started_at.desc())
            .label("rank")
        )
        run_count = func.count().over(partition_by=RunRow.thread_id).label("run_count")
        inner = select(
            RunRow.thread_id, RunRow.flow_slug, RunRow.status, RunRow.started_at, rank, run_count
        )
        if flow_slug:
            inner = inner.where(RunRow.flow_slug == flow_slug)
        ranked = inner.subquery()
        stmt = (
            select(ranked)
            .where(ranked.c.rank == 1)
            .order_by(ranked.c.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).all()
        return [
            {
                "thread_id": row.thread_id,
                "flow_slug": row.flow_slug,
                "runs": row.run_count,
                "last_run_at": row.started_at.isoformat(),
                "last_status": row.status,
            }
            for row in rows
        ]

    async def mark_cancelled_if_active(self, run_id: str) -> bool:
        """Fallback cancel for a run with no live executor task (e.g. after a
        restart): flips an active row to cancelled/RT104 (SPEC §6.1)."""
        async with self._sessions() as session:
            row = await session.get(RunRow, run_id)
            if row is None or row.status not in ("pending", "running", "input_required"):
                return False
            row.status = "cancelled"
            row.error_code = "RT104"
            row.finished_at = datetime.now(UTC)
            await session.commit()
            return True

    # ---------------------------------------------------------------- events
    async def persist_event(self, event: RunEvent) -> None:
        async with self._sessions() as session:
            session.add(
                RunEventRow(
                    run_id=event.run_id,
                    seq=event.seq,
                    payload=json.loads(event.model_dump_json()),
                )
            )
            await session.commit()

    async def load_events(self, run_id: str, after_seq: int = 0) -> builtins.list[RunEvent]:
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(RunEventRow)
                        .where(RunEventRow.run_id == run_id, RunEventRow.seq > after_seq)
                        .order_by(RunEventRow.seq)
                    )
                )
                .scalars()
                .all()
            )
        return [RunEvent.model_validate(r.payload) for r in rows]

    async def max_seq(self, run_id: str) -> int:
        events = await self.load_events(run_id)
        return events[-1].seq if events else 0

    async def delete(self, run_id: str) -> bool:
        """Delete one run trace (row + events). Caller guards active runs."""
        async with self._sessions() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                return False
            await session.execute(delete(RunEventRow).where(RunEventRow.run_id == run_id))
            await session.delete(row)
            await session.commit()
            return True

    async def delete_finished(self, flow_id: str | None = None) -> int:
        """Bulk-delete non-active run traces (optionally scoped to one flow).

        input_required counts as clearable: the trace goes away, the underlying
        thread checkpoint stays intact (A2A tasks are unaffected).
        """
        clearable = (*TERMINAL_STATUSES, "input_required")
        async with self._sessions() as session:
            stmt = select(RunRow).where(RunRow.status.in_(clearable))
            if flow_id:
                stmt = stmt.where(RunRow.flow_id == flow_id)
            rows = (await session.execute(stmt)).scalars().all()
            for row in rows:
                await session.execute(delete(RunEventRow).where(RunEventRow.run_id == row.id))
                await session.delete(row)
            await session.commit()
            return len(rows)

    async def sweep_expired(self) -> int:
        """7d event retention (SPEC §6.2) — called by the lifespan sweeper."""
        cutoff = datetime.now(UTC) - timedelta(days=EVENT_TTL_DAYS)
        async with self._sessions() as session:
            result = await session.execute(
                delete(RunEventRow).where(RunEventRow.created_at < cutoff)
            )
            await session.commit()
            return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def sweep_checkpoints(self, checkpointer: Any, ttl_days: int) -> int:
        """Delete durable checkpoints for threads idle past the TTL (SPEC §6.3).

        The run_events sweeper only trims events; without this the LangGraph
        checkpoint state grows unbounded. A thread is stale when its most-recent
        run started before the cutoff AND it has no non-terminal run — an
        interrupted HITL task is left alone until it, too, ages out, so a paused
        approval is never swept out from under a slow human.
        """
        cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
        active = select(RunRow.thread_id).where(RunRow.status.not_in(TERMINAL_STATUSES))
        async with self._sessions() as session:
            result = await session.execute(
                select(RunRow.thread_id)
                .where(RunRow.thread_id.not_in(active))
                .group_by(RunRow.thread_id)
                .having(func.max(RunRow.started_at) < cutoff)
            )
            stale = [row[0] for row in result.all()]
        removed = 0
        for thread_id in stale:
            with contextlib.suppress(Exception):
                await checkpointer.adelete_thread(thread_id)
                removed += 1
        return removed
