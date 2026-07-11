"""Unit tests for lga.services.runs (SPEC §6.2, §9.3): run rows, status
transitions, event persistence, thread grouping, and the retention sweepers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from lga.db.models import RunEventRow, RunRow
from lga.schema.events import RunEvent
from lga.services.runs import RunService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from lga.services.settings import Settings

SqliteStack = tuple["Settings", "async_sessionmaker[AsyncSession]"]


@pytest.fixture
def runs(sqlite_stack: SqliteStack) -> RunService:
    _settings, sessions = sqlite_stack
    return RunService(sessions)


class FakeCheckpointer:
    """Minimal checkpointer recording which threads were deleted."""

    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.deleted: list[str] = []
        self._fail = fail or set()

    async def adelete_thread(self, thread_id: str) -> None:
        if thread_id in self._fail:
            raise RuntimeError("boom")
        self.deleted.append(thread_id)


# --------------------------------------------------------------------- rows
async def test_create_and_get(runs: RunService) -> None:
    await runs.create("r1", thread_id="t1", mode="api", flow_slug="hello")
    row = await runs.get("r1")
    assert row is not None
    assert row.status == "pending"
    assert row.thread_id == "t1"
    assert row.flow_slug == "hello"


async def test_get_missing_is_none(runs: RunService) -> None:
    assert await runs.get("nope") is None


async def test_update_status_terminal_sets_finished(runs: RunService) -> None:
    await runs.create("r1", thread_id="t1", mode="api")
    await runs.update_status(
        "r1", "completed", result_preview="hi", error_message="ignored-when-not-set"
    )
    row = await runs.get("r1")
    assert row is not None
    assert row.status == "completed"
    assert row.finished_at is not None
    assert row.result_preview == "hi"


async def test_update_status_failed_records_error(runs: RunService) -> None:
    await runs.create("r1", thread_id="t1", mode="api")
    await runs.update_status("r1", "failed", error_code="RT001", error_message="x" * 5000)
    row = await runs.get("r1")
    assert row is not None
    assert row.error_code == "RT001"
    assert len(row.error_message or "") == 2000  # truncated


async def test_update_status_failed_persists_node_id(runs: RunService) -> None:
    # SPEC §5.6: every RT error carries node_id and is stored on the run
    await runs.create("r1", thread_id="t1", mode="api")
    await runs.update_status(
        "r1", "failed", error_code="RT103", error_message="boom", node_id="fake"
    )
    row = await runs.get("r1")
    assert row is not None
    assert row.status == "failed"
    assert row.node_id == "fake"


async def test_update_status_without_node_id_leaves_it_null(runs: RunService) -> None:
    await runs.create("r1", thread_id="t1", mode="api")
    await runs.update_status("r1", "completed", result_preview="ok")
    row = await runs.get("r1")
    assert row is not None
    assert row.node_id is None


async def test_update_status_missing_run_is_noop(runs: RunService) -> None:
    await runs.update_status("ghost", "completed")  # must not raise


async def test_session_opens_working_session_on_shared_db(runs: RunService) -> None:
    # public seam used by the orchestrator instead of touching runs._sessions
    await runs.create("r1", thread_id="t1", mode="api")
    async with runs.session() as session:
        row = await session.get(RunRow, "r1")
    assert row is not None
    assert row.id == "r1"


async def test_list_orders_and_filters(runs: RunService) -> None:
    await runs.create("r1", thread_id="t1", mode="api", flow_id="f1")
    await runs.create("r2", thread_id="t2", mode="api", flow_id="f2")
    assert {r.id for r in await runs.list()} == {"r1", "r2"}
    assert {r.id for r in await runs.list(flow_id="f1")} == {"r1"}


async def test_list_threads_groups_runs(runs: RunService) -> None:
    await runs.create("r1", thread_id="t1", mode="api", flow_slug="hello")
    await runs.create("r2", thread_id="t1", mode="api", flow_slug="hello")
    await runs.create("r3", thread_id="t2", mode="api", flow_slug="other")
    threads = await runs.list_threads()
    by_id = {t["thread_id"]: t for t in threads}
    assert by_id["t1"]["runs"] == 2
    assert by_id["t2"]["runs"] == 1
    # slug filter narrows the set
    only_hello = await runs.list_threads(flow_slug="hello")
    assert {t["thread_id"] for t in only_hello} == {"t1"}


# --------------------------------------------------------------------- events
async def test_persist_load_and_max_seq(runs: RunService) -> None:
    await runs.create("r1", thread_id="t1", mode="api")
    for seq in (1, 2, 3):
        await runs.persist_event(RunEvent(event="node_started", run_id="r1", seq=seq))
    loaded = await runs.load_events("r1")
    assert [e.seq for e in loaded] == [1, 2, 3]
    assert await runs.max_seq("r1") == 3
    # after_seq skips earlier events
    assert [e.seq for e in await runs.load_events("r1", after_seq=2)] == [3]


async def test_max_seq_empty_is_zero(runs: RunService) -> None:
    assert await runs.max_seq("r1") == 0


# --------------------------------------------------------------------- delete
async def test_delete_run_and_events(runs: RunService) -> None:
    await runs.create("r1", thread_id="t1", mode="api")
    await runs.persist_event(RunEvent(event="run_finished", run_id="r1", seq=1))
    assert await runs.delete("r1") is True
    assert await runs.get("r1") is None
    assert await runs.load_events("r1") == []
    assert await runs.delete("r1") is False  # gone already


async def test_delete_finished_clears_only_clearable(runs: RunService) -> None:
    await runs.create("done", thread_id="t1", mode="api", flow_id="f1")
    await runs.update_status("done", "completed")
    await runs.create("wait", thread_id="t2", mode="api", flow_id="f1")
    await runs.update_status("wait", "input_required")
    await runs.create("live", thread_id="t3", mode="api", flow_id="f1")
    await runs.update_status("live", "running")

    removed = await runs.delete_finished(flow_id="f1")
    assert removed == 2  # completed + input_required, not the running one
    assert await runs.get("live") is not None
    assert await runs.get("done") is None
    assert await runs.get("wait") is None


# --------------------------------------------------------------------- sweepers
async def _insert_event(
    sessions: async_sessionmaker[AsyncSession], run_id: str, seq: int, created_at: datetime
) -> None:
    payload = RunEvent(event="node_started", run_id=run_id, seq=seq).model_dump()
    async with sessions() as session:
        session.add(RunEventRow(run_id=run_id, seq=seq, payload=payload, created_at=created_at))
        await session.commit()


async def test_sweep_expired_deletes_old_events_only(
    sqlite_stack: SqliteStack, runs: RunService
) -> None:
    _settings, sessions = sqlite_stack
    now = datetime.now(UTC)
    await _insert_event(sessions, "r1", 1, now - timedelta(days=30))  # stale
    await _insert_event(sessions, "r1", 2, now)  # fresh
    removed = await runs.sweep_expired()
    assert removed == 1
    assert [e.seq for e in await runs.load_events("r1")] == [2]


async def _insert_run(
    sessions: async_sessionmaker[AsyncSession],
    run_id: str,
    thread_id: str,
    status: str,
    started_at: datetime,
) -> None:
    async with sessions() as session:
        session.add(
            RunRow(
                id=run_id,
                thread_id=thread_id,
                mode="api",
                status=status,
                started_at=started_at,
            )
        )
        await session.commit()


async def test_sweep_checkpoints_removes_only_stale_terminal_threads(
    sqlite_stack: SqliteStack, runs: RunService
) -> None:
    _settings, sessions = sqlite_stack
    now = datetime.now(UTC)
    old = now - timedelta(days=40)
    # stale + terminal → swept
    await _insert_run(sessions, "r1", "stale", "completed", old)
    # stale but still has a non-terminal run → left alone (paused HITL)
    await _insert_run(sessions, "r2", "paused", "input_required", old)
    # terminal but recent → left alone
    await _insert_run(sessions, "r3", "recent", "completed", now)

    checkpointer = FakeCheckpointer()
    removed = await runs.sweep_checkpoints(checkpointer, ttl_days=30)
    assert removed == 1
    assert checkpointer.deleted == ["stale"]


async def test_sweep_checkpoints_suppresses_delete_errors(
    sqlite_stack: SqliteStack, runs: RunService
) -> None:
    _settings, sessions = sqlite_stack
    old = datetime.now(UTC) - timedelta(days=40)
    await _insert_run(sessions, "r1", "boomthread", "completed", old)
    checkpointer = FakeCheckpointer(fail={"boomthread"})
    # the raise is swallowed → nothing counted, no exception propagates
    assert await runs.sweep_checkpoints(checkpointer, ttl_days=30) == 0
