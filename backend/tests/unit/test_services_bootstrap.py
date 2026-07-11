"""Unit tests for langgraph_agent_builder.services.bootstrap (SPEC §18.1): starter-flow seeding,
disk flow import (skip/overwrite/auto-publish), and the component-watch guard."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from langgraph_agent_builder.services.bootstrap import (
    load_flows_from_path,
    seed_starter_flows,
    watch_component_dirs,
)
from tests.conftest import hello_spec

if TYPE_CHECKING:
    from pathlib import Path

    from langgraph_agent_builder.app import AppServices


# --------------------------------------------------------------------- seeding
async def test_seed_disabled_returns_zero(svc: AppServices) -> None:
    svc.settings.create_starter_flows = False
    assert await seed_starter_flows(svc) == 0
    assert await svc.flows.list() == []


async def test_seed_populates_empty_db(svc: AppServices) -> None:
    svc.settings.create_starter_flows = True
    created = await seed_starter_flows(svc)
    assert created == 2
    slugs = {f.slug for f in await svc.flows.list()}
    assert {"starter-hello", "starter-approval"} <= slugs


async def test_seed_skips_when_db_not_empty(svc: AppServices) -> None:
    svc.settings.create_starter_flows = True
    await svc.flows.create(hello_spec("preexisting"))
    assert await seed_starter_flows(svc) == 0
    assert len(await svc.flows.list()) == 1  # untouched


# --------------------------------------------------------------------- load_flows_from_path
async def test_load_path_none_returns_zero(svc: AppServices) -> None:
    svc.settings.load_flows_path = None
    assert await load_flows_from_path(svc) == 0


async def test_load_path_not_a_directory_returns_zero(svc: AppServices, tmp_path: Path) -> None:
    not_dir = tmp_path / "file.json"
    not_dir.write_text("{}", encoding="utf-8")
    svc.settings.load_flows_path = not_dir
    assert await load_flows_from_path(svc) == 0


async def test_load_imports_valid_and_skips_invalid(svc: AppServices, tmp_path: Path) -> None:
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    (flows_dir / "good.json").write_text(json.dumps(hello_spec("disk-flow")), encoding="utf-8")
    (flows_dir / "bad.json").write_text("{ not valid json", encoding="utf-8")
    svc.settings.load_flows_path = flows_dir
    svc.settings.load_flows_publish = False

    loaded = await load_flows_from_path(svc)
    assert loaded == 1  # invalid file skipped
    assert await svc.flows.get_by_slug("disk-flow") is not None


async def test_load_existing_skip_vs_overwrite(svc: AppServices, tmp_path: Path) -> None:
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    (flows_dir / "f.json").write_text(
        json.dumps(hello_spec("dupe", description="from disk")), encoding="utf-8"
    )
    svc.settings.load_flows_path = flows_dir
    svc.settings.load_flows_publish = False

    # pre-existing flow with a different description
    await svc.flows.create(hello_spec("dupe", description="original"))

    svc.settings.load_flows_overwrite = False
    assert await load_flows_from_path(svc) == 0  # existing → skipped
    row = await svc.flows.get_by_slug("dupe")
    assert row is not None
    assert row.description == "original"

    svc.settings.load_flows_overwrite = True
    assert await load_flows_from_path(svc) == 1  # existing → overwritten
    row = await svc.flows.get_by_slug("dupe")
    assert row is not None
    assert row.description == "from disk"


async def test_load_auto_publishes_when_enabled(svc: AppServices, tmp_path: Path) -> None:
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    (flows_dir / "pub.json").write_text(json.dumps(hello_spec("autopub")), encoding="utf-8")
    svc.settings.load_flows_path = flows_dir
    svc.settings.load_flows_publish = True

    assert await load_flows_from_path(svc) == 1
    flow = await svc.flows.get_by_slug("autopub")
    assert flow is not None
    assert await svc.flows.latest_version(flow.id) is not None  # published a version


# --------------------------------------------------------------------- watch guard
async def test_watch_component_dirs_no_dirs_returns_immediately(svc: AppServices) -> None:
    svc.settings.components_path = ""  # no component dirs configured
    assert svc.settings.component_dirs() == []  # precondition for the early-return branch
    # early return: must complete without blocking on a filesystem watch
    await watch_component_dirs(svc)
