"""FlowService domain errors (SPEC §9.1): slug uniqueness is enforced by the
UNIQUE constraint (race-safe, no TOCTOU pre-check) and surfaces as
SlugConflictError; locked flows refuse edits with FlowLockedError. The
exception-handler layer in lga.app maps these to 409."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from lga.errors import LgaError
from lga.services.errors import ConflictError, FlowLockedError, SlugConflictError
from lga.services.flows import FlowService

if TYPE_CHECKING:
    from tests.unit.conftest import SqliteStack


def _spec(slug: str, description: str = "a flow") -> dict[str, Any]:
    return {
        "schema_version": "1",
        "flow": {"name": slug, "slug": slug, "description": description},
        "nodes": [
            {
                "id": "start",
                "component_id": "lga.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lga.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 300, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "end", "input": "message"},
            }
        ],
    }


@pytest.fixture
def flows(sqlite_stack: SqliteStack) -> FlowService:
    _settings, sessions = sqlite_stack
    return FlowService(sessions)


async def test_create_duplicate_slug_raises_conflict(flows: FlowService) -> None:
    await flows.create(_spec("dup"))
    with pytest.raises(SlugConflictError, match="already exists"):
        await flows.create(_spec("dup"))


async def test_update_to_taken_slug_raises_conflict(flows: FlowService) -> None:
    await flows.create(_spec("taken"))
    mover = await flows.create(_spec("mover"))
    with pytest.raises(SlugConflictError, match="already exists"):
        await flows.update(mover.id, _spec("taken"))


async def test_update_keeping_own_slug_is_fine(flows: FlowService) -> None:
    row = await flows.create(_spec("same", description="v1"))
    updated = await flows.update(row.id, _spec("same", description="v2"))
    assert updated is not None
    assert updated.description == "v2"


async def test_update_locked_flow_raises(flows: FlowService) -> None:
    row = await flows.create(_spec("frozen"))
    await flows.set_locked(row.id, True)
    with pytest.raises(FlowLockedError, match="locked"):
        await flows.update(row.id, _spec("frozen", description="nope"))


async def test_domain_errors_are_lga_errors(flows: FlowService) -> None:
    # `except LgaError` catches everything the domain raises on purpose
    assert issubclass(SlugConflictError, ConflictError)
    assert issubclass(FlowLockedError, ConflictError)
    assert issubclass(ConflictError, LgaError)


async def test_latest_versions_batch_matches_per_flow(flows: FlowService) -> None:
    from lga.sdk.registry import get_registry

    a = await flows.create(_spec("batch-a"))
    b = await flows.create(_spec("batch-b"))
    unpublished = await flows.create(_spec("batch-c"))
    await flows.publish(a.id, registry=get_registry(), bump="minor")  # 0.1.0
    await flows.publish(a.id, registry=get_registry(), bump="minor")  # 0.2.0
    await flows.publish(b.id, registry=get_registry(), bump="patch")  # 0.0.1

    latest = await flows.latest_versions([a.id, b.id, unpublished.id])
    assert latest[a.id].semver == "0.2.0"
    assert latest[b.id].semver == "0.0.1"
    assert unpublished.id not in latest
    assert await flows.latest_versions([]) == {}


async def test_list_query_and_pagination(flows: FlowService) -> None:
    for slug in ("alpha-one", "alpha-two", "beta-one"):
        await flows.create(_spec(slug))
    hits = await flows.list(q="ALPHA")
    assert {r.slug for r in hits} == {"alpha-one", "alpha-two"}
    page = await flows.list(limit=2)
    assert len(page) == 2
    rest = await flows.list(limit=2, offset=2)
    assert len(rest) == 1
