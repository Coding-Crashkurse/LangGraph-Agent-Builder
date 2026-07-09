"""Boot-time provisioning (SPEC §18.1): load flows from disk, starter flows,
dev hot-reload of component dirs."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from lga.schema.flowspec import FlowSpecError, parse_flowspec

if TYPE_CHECKING:
    from lga.app import AppServices

logger = logging.getLogger("lga.bootstrap")

STARTER_FLOWS: list[dict[str, Any]] = [
    {
        "schema_version": "2",
        "flow": {
            "name": "Starter: Hello",
            "slug": "starter-hello",
            "description": "Minimal flow: start → Fake LLM → end. Runs without API keys.",
            "a2a": {"enabled": False, "description": "Replies with a scripted greeting."},
        },
        "nodes": [
            {
                "id": "start",
                "component_id": "lga.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 120},
            },
            {
                "id": "fake_llm",
                "component_id": "lga.testing.fake_llm",
                "component_version": "1.0.0",
                "config": {"replies": ["Hello from lga! Wire in a real model when ready."]},
                "position": {"x": 320, "y": 120},
            },
            {
                "id": "end",
                "component_id": "lga.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 660, "y": 120},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "fake_llm", "input": "input"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "fake_llm", "output": "message"},
                "target": {"node": "end", "input": "message"},
            },
        ],
    },
    {
        "schema_version": "2",
        "flow": {
            "name": "Starter: Human Approval",
            "slug": "starter-approval",
            "description": "HITL template: draft → human approval → release or retry.",
            "a2a": {"enabled": False, "description": "Draft, approve, release."},
        },
        "nodes": [
            {
                "id": "start",
                "component_id": "lga.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 140},
            },
            {
                "id": "draft",
                "component_id": "lga.testing.fake_llm",
                "component_version": "1.0.0",
                "config": {"replies": ["Draft answer — replace me with LLM Call."]},
                "position": {"x": 280, "y": 140},
            },
            {
                "id": "review",
                "component_id": "lga.flow.human_approval",
                "component_version": "1.0.0",
                "config": {"prompt": "Release this answer?"},
                "position": {"x": 580, "y": 140},
            },
            {
                "id": "end",
                "component_id": "lga.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 900, "y": 80},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "draft", "input": "input"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "draft", "output": "message"},
                "target": {"node": "review", "input": "input"},
            },
            {
                "id": "e3",
                "kind": "router",
                "source": {"node": "review", "output": "approve"},
                "target": {"node": "end", "input": "message"},
            },
            {
                "id": "e4",
                "kind": "router",
                "source": {"node": "review", "output": "reject"},
                "target": {"node": "draft", "input": "input"},
            },
        ],
    },
]


async def seed_starter_flows(svc: AppServices) -> int:
    """Seed bundled templates into an EMPTY database (LGA_CREATE_STARTER_FLOWS)."""
    if not svc.settings.create_starter_flows:
        return 0
    if await svc.flows.list():
        return 0
    created = 0
    for spec in STARTER_FLOWS:
        try:
            await svc.flows.create(parse_flowspec(spec))
            created += 1
        except Exception:
            logger.exception("failed to seed starter flow %s", spec["flow"]["slug"])
    if created:
        logger.info("seeded %d starter flows", created)
    return created


async def load_flows_from_path(svc: AppServices) -> int:
    """Import FlowSpec *.json from LGA_LOAD_FLOWS_PATH at boot (SPEC §18.1)."""
    path = svc.settings.load_flows_path
    if path is None:
        return 0
    path = path.expanduser()
    if not path.is_dir():
        logger.warning("LGA_LOAD_FLOWS_PATH %s is not a directory", path)
        return 0
    loaded = 0
    for file in sorted(path.glob("*.json")):
        try:
            spec = parse_flowspec(json.loads(file.read_text(encoding="utf-8")))
        except (FlowSpecError, ValueError) as exc:
            logger.warning("skipping %s: %s", file.name, exc)
            continue
        existing = await svc.flows.get_by_slug(spec.flow.slug)
        if existing is not None:
            if not svc.settings.load_flows_overwrite:
                logger.info("flow %s exists — skipped (%s)", spec.flow.slug, file.name)
                continue
            flow = await svc.flows.update(existing.id, spec)
        else:
            flow = await svc.flows.create(spec)
        loaded += 1
        if svc.settings.load_flows_publish and flow is not None:
            diags, _compiled = await svc.orchestrator.validate(flow.spec)
            version, all_diags = await svc.flows.publish(
                flow.id,
                registry=svc.registry,
                bump="patch",
                changelog=f"auto-published from {file.name}",
                compile_diagnostics=diags,
            )
            if version is None:
                logger.warning(
                    "auto-publish blocked for %s: %s",
                    spec.flow.slug,
                    "; ".join(
                        f"{d.code.value} {d.message}" for d in all_diags if d.severity == "error"
                    ),
                )
    if loaded:
        logger.info("loaded %d flows from %s", loaded, path)
    return loaded


async def watch_component_dirs(svc: AppServices) -> None:
    """Dev hot-reload (SPEC §4.8-3/§18.2): re-import changed component files."""
    dirs = [d for d in svc.settings.component_dirs() if d.is_dir()]
    if not dirs:
        return
    try:
        from watchfiles import awatch
    except ImportError:  # pragma: no cover
        logger.warning("watchfiles not installed — component hot-reload disabled")
        return
    logger.info("watching component dirs for changes: %s", ", ".join(map(str, dirs)))
    async for changes in awatch(*dirs):
        touched = {c[1] for c in changes if c[1].endswith(".py")}
        if not touched:
            continue
        try:
            for directory in dirs:
                svc.registry._scan_dir(directory)
            from lga.compiler import clear_compile_cache

            clear_compile_cache()
            logger.info(
                "component dirs reloaded (%d files changed) — etag %s",
                len(touched),
                svc.registry.etag(),
            )
        except Exception:
            logger.exception("component hot-reload failed")
        await asyncio.sleep(0.2)  # debounce bursts
