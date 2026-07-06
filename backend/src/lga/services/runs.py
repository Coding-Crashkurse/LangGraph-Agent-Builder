"""Run bookkeeping + event persistence glue (SPEC §6.2, §9.3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
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

    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        result_preview: str | None = None,
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
            if result_preview is not None:
                row.result_preview = result_preview
            if status in TERMINAL_STATUSES:
                row.finished_at = datetime.now(UTC)
            await session.commit()

    async def get(self, run_id: str) -> RunRow | None:
        async with self._sessions() as session:
            return await session.get(RunRow, run_id)

    async def list(self, flow_id: str | None = None, limit: int = 100) -> list[RunRow]:
        async with self._sessions() as session:
            stmt = select(RunRow).order_by(RunRow.started_at.desc()).limit(limit)
            if flow_id:
                stmt = stmt.where(RunRow.flow_id == flow_id)
            return list((await session.execute(stmt)).scalars().all())

    async def list_threads(self, flow_slug: str | None = None) -> list[dict[str, Any]]:
        runs = await self.list(limit=1000)
        threads: dict[str, dict[str, Any]] = {}
        for run in runs:
            if flow_slug and run.flow_slug != flow_slug:
                continue
            t = threads.setdefault(
                run.thread_id,
                {
                    "thread_id": run.thread_id,
                    "flow_slug": run.flow_slug,
                    "runs": 0,
                    "last_run_at": run.started_at.isoformat(),
                    "last_status": run.status,
                },
            )
            t["runs"] += 1
        return list(threads.values())

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

    async def load_events(self, run_id: str, after_seq: int = 0) -> list[RunEvent]:
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

    async def sweep_expired(self) -> int:
        """7d event retention (SPEC §6.2) — called by the lifespan sweeper."""
        cutoff = datetime.now(UTC) - timedelta(days=EVENT_TTL_DAYS)
        async with self._sessions() as session:
            result = await session.execute(
                delete(RunEventRow).where(RunEventRow.created_at < cutoff)
            )
            await session.commit()
            return int(result.rowcount or 0)
