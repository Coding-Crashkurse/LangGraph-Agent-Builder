"""Unit tests for lga.a2a.tasks — DbTaskStore persistence, the explicit
transition state machine (SPEC §7.6), scope namespacing (§7.11), and the
pluggable ``resolve_task_store`` factory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from a2a.server.context import ServerCallContext
from a2a.server.tasks import InMemoryTaskStore, TaskStore
from a2a.types import Message, Part, Role, Task, TaskState, TaskStatus, TextPart

from lga.a2a.tasks import (
    DbTaskStore,
    IllegalTaskTransitionError,
    resolve_task_store,
)

if TYPE_CHECKING:
    from tests.unit.conftest import SqliteStack


def _task(task_id: str, state: TaskState, context_id: str = "ctx-1") -> Task:
    return Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=state),
        history=[Message(role=Role.user, message_id="m1", parts=[Part(root=TextPart(text="hi"))])],
    )


# ---- module-level factories for the dotted-path resolve_task_store variant ----
def good_factory(**_kwargs: Any) -> TaskStore:
    return InMemoryTaskStore()


def bad_factory(**_kwargs: Any) -> str:
    return "not a task store"


# --------------------------------------------------------------------- store


async def test_save_creates_row_and_initial_transition(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    store = DbTaskStore(sessions, "flow-a")
    await store.save(_task("t1", TaskState.submitted))

    got = await store.get("t1")
    assert got is not None
    assert got.id == "t1"
    assert got.status.state == TaskState.submitted

    trans = await store.transitions("t1")
    assert len(trans) == 1
    assert trans[0]["from"] == ""
    assert trans[0]["to"] == "submitted"


async def test_legal_transition_records_history(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    store = DbTaskStore(sessions, "flow-a")
    await store.save(_task("t2", TaskState.submitted))
    await store.save(_task("t2", TaskState.working))
    await store.save(_task("t2", TaskState.completed))

    states = [t["to"] for t in await store.transitions("t2")]
    assert states == ["submitted", "working", "completed"]
    got = await store.get("t2")
    assert got is not None
    assert got.status.state == TaskState.completed


async def test_illegal_transition_raises_and_leaves_state(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    store = DbTaskStore(sessions, "flow-a")
    await store.save(_task("t3", TaskState.submitted))
    await store.save(_task("t3", TaskState.working))
    await store.save(_task("t3", TaskState.completed))

    with pytest.raises(IllegalTaskTransitionError):
        await store.save(_task("t3", TaskState.working))  # completed is terminal

    got = await store.get("t3")
    assert got is not None
    assert got.status.state == TaskState.completed  # unchanged


async def test_delete_removes_row(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    store = DbTaskStore(sessions, "flow-a")
    await store.save(_task("t4", TaskState.submitted))
    await store.delete("t4")
    assert await store.get("t4") is None
    # deleting an unknown id is a no-op, not an error
    await store.delete("t4")


async def test_list_tasks_scoped_to_flow(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    store_a = DbTaskStore(sessions, "flow-a")
    store_b = DbTaskStore(sessions, "flow-b")
    await store_a.save(_task("a1", TaskState.submitted))
    await store_a.save(_task("a2", TaskState.submitted))
    await store_b.save(_task("b1", TaskState.submitted))

    listed = await store_a.list_tasks()
    ids = {row["task_id"] for row in listed}
    assert ids == {"a1", "a2"}
    row = next(r for r in listed if r["task_id"] == "a1")
    assert row["state"] == "submitted"
    assert row["context_id"] == "ctx-1"
    assert "created_at" in row
    assert "updated_at" in row


# --------------------------------------------------------------------- scope


async def test_context_scope_namespacing(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    store = DbTaskStore(sessions, "flow-a")
    owner = ServerCallContext(state={"lga_client_scope": "scope-owner"})
    other = ServerCallContext(state={"lga_client_scope": "scope-other"})

    await store.save(_task("s1", TaskState.submitted), context=owner)
    # same scope sees it
    assert (await store.get("s1", context=owner)) is not None
    # a foreign public session behaves as if the task does not exist (§7.11)
    assert (await store.get("s1", context=other)) is None


async def test_resave_same_state_adds_no_transition(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    store = DbTaskStore(sessions, "flow-a")
    await store.save(_task("r1", TaskState.working, context_id="c1"))
    await store.save(_task("r1", TaskState.working, context_id="c2"))  # same state

    trans = await store.transitions("r1")
    assert [t["to"] for t in trans] == ["working"]  # no duplicate transition row
    got = await store.get("r1")
    assert got is not None
    assert got.context_id == "c2"  # snapshot updated in place


async def test_context_without_scope_key_falls_back(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    store = DbTaskStore(sessions, "flow-a")
    # context carries unrelated state → scope resolution falls back to the
    # (empty) contextvar rather than raising or namespacing.
    ctx = ServerCallContext(state={"user": "someone"})
    await store.save(_task("u1", TaskState.submitted), context=ctx)
    got = await store.get("u1", context=ctx)
    assert got is not None
    assert got.id == "u1"


# --------------------------------------------------------------- resolve


async def test_resolve_default_and_db_return_dbtaskstore(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    for setting in ("", "db"):
        store = resolve_task_store(setting, sessions=sessions, flow_slug="f")
        assert isinstance(store, DbTaskStore)


async def test_resolve_memory_returns_in_memory(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    store = resolve_task_store("memory", sessions=sessions, flow_slug="f")
    assert isinstance(store, InMemoryTaskStore)


async def test_resolve_dotted_factory(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    store = resolve_task_store(
        "tests.unit.test_a2a_tasks:good_factory", sessions=sessions, flow_slug="f"
    )
    assert isinstance(store, InMemoryTaskStore)


async def test_resolve_dotted_without_attr_is_value_error(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    with pytest.raises(ValueError, match="invalid LGA_A2A_TASK_STORE"):
        resolve_task_store("just_a_module", sessions=sessions, flow_slug="f")


async def test_resolve_factory_wrong_type_is_type_error(sqlite_stack: SqliteStack) -> None:
    _settings, sessions = sqlite_stack
    with pytest.raises(TypeError, match="did not return an a2a TaskStore"):
        resolve_task_store(
            "tests.unit.test_a2a_tasks:bad_factory", sessions=sessions, flow_slug="f"
        )
