"""RunService thread queries (SPEC §6.3): SQL aggregation replaces the old
load-1000-and-scan approach, so threads resolve regardless of run volume, plus
the RT104 fallback-cancel state rule (SPEC §6.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lga.services.runs import RunService

if TYPE_CHECKING:
    from tests.unit.conftest import SqliteStack


@pytest.fixture
def runs(sqlite_stack: SqliteStack) -> RunService:
    _settings, sessions = sqlite_stack
    return RunService(sessions)


async def test_get_by_thread_returns_newest_run(runs: RunService) -> None:
    await runs.create("r1", thread_id="t1", mode="api", flow_slug="hello")
    await runs.create("r2", thread_id="t1", mode="api", flow_slug="hello")
    await runs.create("r3", thread_id="t2", mode="api", flow_slug="other")

    newest = await runs.get_by_thread("t1")
    assert newest is not None
    assert newest.id == "r2"  # started later
    assert await runs.get_by_thread("no-such-thread") is None


async def test_list_threads_last_status_comes_from_newest_run(runs: RunService) -> None:
    await runs.create("r1", thread_id="t1", mode="api", flow_slug="hello")
    await runs.update_status("r1", "completed")
    await runs.create("r2", thread_id="t1", mode="api", flow_slug="hello")
    await runs.update_status("r2", "failed")

    threads = await runs.list_threads()
    assert len(threads) == 1
    thread = threads[0]
    assert thread["thread_id"] == "t1"
    assert thread["runs"] == 2
    assert thread["last_status"] == "failed"  # newest run, not an ordering accident


async def test_list_threads_pagination_newest_first(runs: RunService) -> None:
    for i in range(3):
        await runs.create(f"r{i}", thread_id=f"t{i}", mode="api", flow_slug="hello")

    first = await runs.list_threads(limit=1)
    assert [t["thread_id"] for t in first] == ["t2"]  # newest activity first
    rest = await runs.list_threads(limit=2, offset=1)
    assert [t["thread_id"] for t in rest] == ["t1", "t0"]


async def test_mark_cancelled_if_active_flips_only_active_runs(runs: RunService) -> None:
    await runs.create("live", thread_id="t1", mode="api")
    await runs.update_status("live", "running")
    assert await runs.mark_cancelled_if_active("live") is True
    row = await runs.get("live")
    assert row is not None
    assert row.status == "cancelled"
    assert row.error_code == "RT104"
    assert row.finished_at is not None

    await runs.create("done", thread_id="t2", mode="api")
    await runs.update_status("done", "completed")
    assert await runs.mark_cancelled_if_active("done") is False
    assert await runs.mark_cancelled_if_active("ghost") is False


async def test_run_list_offset(runs: RunService) -> None:
    for i in range(3):
        await runs.create(f"r{i}", thread_id=f"t{i}", mode="api")
    newest_first = [r.id for r in await runs.list(limit=2)]
    assert newest_first == ["r2", "r1"]
    assert [r.id for r in await runs.list(limit=2, offset=2)] == ["r0"]
