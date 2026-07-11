"""Run bookkeeping + event persistence glue (SPEC §6.2, §9.3)."""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from langgraph_agent_builder.db.models import NodeRunRow, RunEventRow, RunRow
from langgraph_agent_builder.schema.events import RunEvent

logger = logging.getLogger("lab.runs")

TERMINAL_STATUSES = ("completed", "failed", "cancelled")
EVENT_TTL_DAYS = 7


class RunService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        # Background writer for the per-node run timeline (REFACTOR.md §7):
        # ``record_node_run`` (sync, called from the compiler wrapper) enqueues
        # here; ``_node_run_loop`` drains it. Mirrors EventBus._persist_loop so
        # DB writes stay off the run's hot path.
        self._node_run_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._node_run_task: asyncio.Task[None] | None = None

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

    # ---------------------------------------------------------------- node runs (§7)
    def record_node_run(self, payload: dict[str, Any]) -> None:
        """Enqueue a node-timeline event for the background writer (sync, §7).

        Called from the compiler node wrapper via ``RunContext.record_node_run``
        with ``{event, run_id, node_id, iteration, ...}``. Non-blocking so it
        never stalls a running node; the DB write happens on ``_node_run_loop``.
        """
        self._ensure_node_run_task()
        self._node_run_queue.put_nowait(payload)

    def _ensure_node_run_task(self) -> None:
        if self._node_run_task is None or self._node_run_task.done():
            self._node_run_task = asyncio.get_running_loop().create_task(self._node_run_loop())

    async def _node_run_loop(self) -> None:
        while True:
            payload = await self._node_run_queue.get()
            try:
                await self._write_node_run(payload)
            except Exception:  # a bad snapshot must never kill the writer
                logger.exception("failed to persist node run %s", payload.get("node_id"))
            finally:
                self._node_run_queue.task_done()

    async def _write_node_run(self, payload: dict[str, Any]) -> None:
        """Upsert one node-timeline row: 'started' inserts, later events update.

        Events for one (run, node, iteration) arrive in order on a single-consumer
        queue, so 'started' is always committed before its 'finished'/'error'/
        'interrupted'. Updates target the still-open ('running') row, so a looped
        or resumed node (same iteration under a fresh RunContext) never clobbers a
        row that already completed.
        """
        run_id = str(payload.get("run_id") or "")
        node_id = str(payload.get("node_id") or "")
        if not run_id or not node_id:
            return
        event = payload.get("event")
        iteration = int(payload.get("iteration") or 0)
        async with self._sessions() as session:
            if event == "started":
                session.add(
                    NodeRunRow(
                        run_id=run_id,
                        node_id=node_id,
                        iteration=iteration,
                        status="running",
                        input_snapshot=payload.get("input_snapshot"),
                    )
                )
                await session.commit()
                return
            row = (
                (
                    await session.execute(
                        select(NodeRunRow)
                        .where(
                            NodeRunRow.run_id == run_id,
                            NodeRunRow.node_id == node_id,
                            NodeRunRow.iteration == iteration,
                            NodeRunRow.status == "running",
                        )
                        .order_by(NodeRunRow.started_at.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                return
            row.finished_at = datetime.now(UTC)
            if payload.get("duration_ms") is not None:
                row.duration_ms = float(payload["duration_ms"])
            if event == "finished":
                row.status = "ok"
                row.output_snapshot = payload.get("output_snapshot")
            elif event == "error":
                row.status = "error"
                row.error_code = payload.get("error_code")
            elif event == "interrupted":
                row.status = "interrupted"
            await session.commit()

    async def list_node_runs(self, run_id: str) -> builtins.list[NodeRunRow]:
        """The run's node timeline, oldest first (REFACTOR.md §7)."""
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(NodeRunRow)
                        .where(NodeRunRow.run_id == run_id)
                        .order_by(NodeRunRow.started_at, NodeRunRow.iteration)
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def drain_node_runs(self) -> None:
        """Flush pending node-timeline writes (tests + graceful shutdown)."""
        if self._node_run_task is not None and not self._node_run_task.done():
            await self._node_run_queue.join()

    async def aclose(self) -> None:
        """Flush queued node-run writes, then stop the writer task (leaving it
        running trips 'Task was destroyed but it is pending')."""
        await self.drain_node_runs()
        if self._node_run_task is not None:
            self._node_run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._node_run_task
            self._node_run_task = None

    async def delete(self, run_id: str) -> bool:
        """Delete one run trace (row + events + node runs). Caller guards active runs."""
        async with self._sessions() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                return False
            await session.execute(delete(RunEventRow).where(RunEventRow.run_id == run_id))
            await session.execute(delete(NodeRunRow).where(NodeRunRow.run_id == run_id))
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
                await session.execute(delete(NodeRunRow).where(NodeRunRow.run_id == row.id))
                await session.delete(row)
            await session.commit()
            return len(rows)

    async def sweep_expired(self) -> int:
        """7d event retention (SPEC §6.2) — called by the lifespan sweeper.

        The per-node timeline (REFACTOR.md §7) is a detail trace like events, so
        it ages out on the same TTL (by ``started_at``); returns the event count.
        """
        cutoff = datetime.now(UTC) - timedelta(days=EVENT_TTL_DAYS)
        async with self._sessions() as session:
            result = await session.execute(
                delete(RunEventRow).where(RunEventRow.created_at < cutoff)
            )
            await session.execute(delete(NodeRunRow).where(NodeRunRow.started_at < cutoff))
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
