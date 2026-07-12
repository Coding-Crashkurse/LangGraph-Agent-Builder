"""Unit tests for langgraph_agent_builder.services.flows (SPEC §9.1): semver bumping, publish guards
(E060-E065), draft CRUD, versioning, publish/rollback, and serving helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from langgraph_agent_builder.schema.diagnostics import DiagnosticCode, has_errors
from langgraph_agent_builder.schema.flowspec import parse_flowspec
from langgraph_agent_builder.sdk.registry import get_registry
from langgraph_agent_builder.services.flows import FlowService, bump_semver, publish_guards

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from langgraph_agent_builder.services.settings import Settings

SqliteStack = tuple["Settings", "async_sessionmaker[AsyncSession]"]


def _spec(
    slug: str = "flow",
    *,
    a2a: dict[str, Any] | None = None,
    mcp: dict[str, Any] | None = None,
    description: str = "a flow",
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    flow: dict[str, Any] = {"name": slug, "slug": slug, "description": description}
    if a2a is not None:
        flow["a2a"] = a2a
    if mcp is not None:
        flow["mcp"] = mcp
    return {
        "schema_version": "1",
        "flow": flow,
        "nodes": nodes
        or [
            {
                "id": "start",
                "component_id": "lab.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lab.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 300, "y": 0},
            },
        ],
        "edges": edges
        if edges is not None
        else [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "end", "input": "result"},
            }
        ],
    }


@pytest.fixture
def flows(sqlite_stack: SqliteStack) -> FlowService:
    _settings, sessions = sqlite_stack
    return FlowService(sessions)


# --------------------------------------------------------------------- bump_semver
def test_bump_semver_major_minor_patch() -> None:
    assert bump_semver("1.2.3", "major") == "2.0.0"
    assert bump_semver("1.2.3", "minor") == "1.3.0"
    assert bump_semver("1.2.3", "patch") == "1.2.4"


def test_bump_semver_explicit_target_wins() -> None:
    assert bump_semver("1.2.3", "5.0.0") == "5.0.0"


def test_bump_semver_invalid_current_defaults_to_zero() -> None:
    assert bump_semver("not-a-version", "minor") == "0.1.0"
    assert bump_semver("", "patch") == "0.0.1"


# --------------------------------------------------------------------- publish_guards
def test_publish_guards_clean_a2a_flow() -> None:
    spec = parse_flowspec(_spec(a2a={"enabled": True, "description": "greet", "examples": ["hi"]}))
    assert publish_guards(spec, get_registry()) == []


def test_publish_guards_e060_missing_a2a_description() -> None:
    spec = parse_flowspec(
        _spec(description="", a2a={"enabled": True, "description": "", "examples": ["hi"]})
    )
    codes = {d.code for d in publish_guards(spec, get_registry())}
    assert DiagnosticCode.E060 in codes


def test_publish_guards_e061_missing_examples_is_warning() -> None:
    spec = parse_flowspec(_spec(a2a={"enabled": True, "description": "greet", "examples": []}))
    diags = publish_guards(spec, get_registry())
    e061 = [d for d in diags if d.code == DiagnosticCode.E061]
    assert len(e061) == 1
    assert e061[0].severity != "error"  # recommendation only, does not block


def test_publish_guards_e062_missing_mcp_description() -> None:
    spec = parse_flowspec(_spec(description="", mcp={"enabled": True, "description": ""}))
    codes = {d.code for d in publish_guards(spec, get_registry())}
    assert DiagnosticCode.E062 in codes


def test_publish_guards_e063_mcp_with_unresolved_interrupt() -> None:
    nodes = [
        {
            "id": "start",
            "component_id": "lab.io.start",
            "component_version": "1.0.0",
            "config": {},
            "position": {"x": 0, "y": 0},
        },
        {
            "id": "review",
            "component_id": "lab.flow.human_approval",
            "component_version": "1.0.0",
            "config": {"prompt": "ok?"},
            "position": {"x": 300, "y": 0},
        },
        {
            "id": "end",
            "component_id": "lab.io.end",
            "component_version": "1.0.0",
            "config": {},
            "position": {"x": 600, "y": 0},
        },
    ]
    edges = [
        {
            "id": "e1",
            "kind": "data",
            "source": {"node": "start", "output": "message"},
            "target": {"node": "review", "input": "input"},
        },
        {
            "id": "e2",
            "kind": "router",
            "source": {"node": "review", "output": "approve"},
            "target": {"node": "end", "input": "result"},
        },
    ]
    spec = parse_flowspec(
        _spec(mcp={"enabled": True, "description": "tool"}, nodes=nodes, edges=edges)
    )
    codes = {d.code for d in publish_guards(spec, get_registry())}
    assert DiagnosticCode.E063 in codes


def _structured_nodes(end_config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "id": "start",
            "component_id": "lab.io.start",
            "component_version": "1.0.0",
            "config": {},
            "position": {"x": 0, "y": 0},
        },
        {
            "id": "end",
            "component_id": "lab.io.end",
            "component_version": "1.0.0",
            "config": end_config or {},
            "position": {"x": 300, "y": 0},
        },
    ]


def _json_edges() -> list[dict[str, Any]]:
    return [
        {
            "id": "e1",
            "kind": "data",
            "source": {"node": "start", "output": "message"},
            "target": {"node": "end", "input": "result"},
        }
    ]


def test_publish_guards_e065_malformed_output_schema_blocks() -> None:
    # fires regardless of the serving door — default api mode here
    malformed = {"type": "object", "properties": {"x": {"type": "not-a-type"}}}
    nodes = _structured_nodes({"output_schema": malformed})
    spec = parse_flowspec(_spec(nodes=nodes, edges=_json_edges()))
    diags = publish_guards(spec, get_registry())
    e065 = [d for d in diags if d.code == DiagnosticCode.E065]
    assert len(e065) == 1
    assert has_errors(e065)  # blocks publish
    assert e065[0].node_id == "end"
    assert e065[0].field == "output_schema"


def test_publish_guards_e064_silent_for_api_door() -> None:
    spec = parse_flowspec(_spec(nodes=_structured_nodes(), edges=_json_edges()))
    codes = {d.code for d in publish_guards(spec, get_registry())}
    assert DiagnosticCode.E064 not in codes


def test_publish_guards_e064_silent_when_schema_declared() -> None:
    nodes = _structured_nodes(
        {"output_schema": {"type": "object", "properties": {"answer": {"type": "string"}}}}
    )
    spec = parse_flowspec(
        _spec(mcp={"enabled": True, "description": "tool"}, nodes=nodes, edges=_json_edges())
    )
    codes = {d.code for d in publish_guards(spec, get_registry())}
    assert DiagnosticCode.E064 not in codes
    assert DiagnosticCode.E065 not in codes


def test_publish_guards_e064_silent_when_structured_inputs_unwired() -> None:
    edges = [
        {
            "id": "e1",
            "kind": "data",
            "source": {"node": "start", "output": "message"},
            "target": {"node": "end", "input": "result"},
        }
    ]
    spec = parse_flowspec(
        _spec(mcp={"enabled": True, "description": "tool"}, nodes=_structured_nodes(), edges=edges)
    )
    codes = {d.code for d in publish_guards(spec, get_registry())}
    assert DiagnosticCode.E064 not in codes


def test_publish_guards_e064_schema_declared_but_unwired_warns() -> None:
    # a declared output contract that can never be fulfilled (nothing wired into
    # the end node's Result input) would hard-fail every MCP/A2A call at runtime
    nodes = _structured_nodes(
        {"output_schema": {"type": "object", "properties": {"answer": {"type": "string"}}}}
    )
    spec = parse_flowspec(
        _spec(mcp={"enabled": True, "description": "tool"}, nodes=nodes, edges=[])
    )
    e064 = [d for d in publish_guards(spec, get_registry()) if d.code == DiagnosticCode.E064]
    assert len(e064) == 1
    assert not has_errors(e064)
    assert "unwired" in e064[0].message


def test_publish_guards_e065_non_dict_output_schema_blocks_without_crash() -> None:
    # a numeric config value must yield E065, not a TypeError → HTTP 500
    nodes = _structured_nodes({"output_schema": 5})
    spec = parse_flowspec(_spec(nodes=nodes, edges=_json_edges()))
    e065 = [d for d in publish_guards(spec, get_registry()) if d.code == DiagnosticCode.E065]
    assert len(e065) == 1
    assert has_errors(e065)
    assert "JSON Schema object" in e065[0].message


def test_publish_guards_e065_covers_start_input_schema() -> None:
    nodes = _structured_nodes()
    nodes[0]["config"]["input_schema"] = {
        "properties": {"x": {"type": "string"}},
        "required": "x",  # must be an array — invalid schema
    }
    spec = parse_flowspec(_spec(nodes=nodes, edges=_json_edges()))
    e065 = [d for d in publish_guards(spec, get_registry()) if d.code == DiagnosticCode.E065]
    assert len(e065) == 1
    assert e065[0].node_id == "start"
    assert e065[0].field == "input_schema"


# --------------------------------------------------------------------- draft CRUD
async def test_create_get_resolve_by_id_and_slug(flows: FlowService) -> None:
    row = await flows.create(_spec("alpha"))
    assert row.slug == "alpha"
    assert await flows.get(row.id) is not None
    by_slug = await flows.get_by_slug("alpha")
    assert by_slug is not None
    assert by_slug.id == row.id
    by_name = await flows.resolve("alpha")
    assert by_name is not None
    assert by_name.id == row.id
    by_id = await flows.resolve(row.id)
    assert by_id is not None
    assert by_id.id == row.id
    assert await flows.resolve("nope") is None


async def test_list_returns_all(flows: FlowService) -> None:
    await flows.create(_spec("a"))
    await flows.create(_spec("b"))
    assert {r.slug for r in await flows.list()} == {"a", "b"}


async def test_update_mutates_row(flows: FlowService) -> None:
    row = await flows.create(_spec("edit", description="old"))
    updated = await flows.update(row.id, _spec("edit", description="new"))
    assert updated is not None
    assert updated.description == "new"


async def test_update_missing_returns_none(flows: FlowService) -> None:
    assert await flows.update("missing-id", _spec("x")) is None


async def test_set_locked_updates_row_and_spec(flows: FlowService) -> None:
    row = await flows.create(_spec("lockme"))
    locked = await flows.set_locked(row.id, True)
    assert locked is not None
    assert locked.locked is True
    assert locked.spec["flow"]["locked"] is True
    assert await flows.set_locked("missing", True) is None


async def test_set_serve_version(flows: FlowService) -> None:
    row = await flows.create(_spec("serve"))
    await flows.set_serve_version(row.id, "1.2.0")
    served = await flows.get(row.id)
    assert served is not None
    assert served.serve_version == "1.2.0"


async def test_delete_removes_flow_and_versions(flows: FlowService) -> None:
    row = await flows.create(_spec("gone"))
    await flows.publish(row.id, registry=get_registry())
    assert await flows.delete(row.id) is True
    assert await flows.get(row.id) is None
    assert await flows.versions(row.id) == []
    assert await flows.delete(row.id) is False  # already gone


# --------------------------------------------------------------------- upgrade_node
async def test_upgrade_node_repins_version(flows: FlowService) -> None:
    nodes = [
        {
            "id": "fake",
            "component_id": "lab.testing.fake_llm",
            "component_version": "0.9.0",
            "config": {"replies": ["hi"]},
            "position": {"x": 0, "y": 0},
        },
    ]
    row = await flows.create(_spec("up", nodes=nodes, edges=[]))
    updated, err = await flows.upgrade_node(row.id, "fake", get_registry())
    assert err is None
    assert updated is not None
    cls = get_registry().get("lab.testing.fake_llm")
    assert cls is not None
    assert updated.spec["nodes"][0]["component_version"] == cls.version


async def test_upgrade_node_errors(flows: FlowService) -> None:
    row = await flows.create(_spec("upe"))
    assert (await flows.upgrade_node("missing", "start", get_registry()))[1] == "flow not found"
    assert (await flows.upgrade_node(row.id, "ghost", get_registry()))[1] == "node not found"


# --------------------------------------------------------------------- publish / versions
async def test_publish_success_and_semver_progression(flows: FlowService) -> None:
    row = await flows.create(_spec("pub"))
    v1, diags = await flows.publish(row.id, registry=get_registry(), bump="minor")
    assert v1 is not None
    assert v1.semver == "0.1.0"
    assert not has_errors(diags)
    v2, _ = await flows.publish(row.id, registry=get_registry(), bump="patch")
    assert v2 is not None
    assert v2.semver == "0.1.1"
    latest = await flows.latest_version(row.id)
    assert latest is not None
    assert latest.semver == "0.1.1"
    assert {v.semver for v in await flows.versions(row.id)} == {"0.1.0", "0.1.1"}


async def test_publish_missing_flow_is_e001(flows: FlowService) -> None:
    version, diags = await flows.publish("no-such-flow", registry=get_registry())
    assert version is None
    assert diags[0].code == DiagnosticCode.E001


async def test_publish_blocked_by_error_diagnostic(flows: FlowService) -> None:
    row = await flows.create(
        _spec("blk", description="", a2a={"enabled": True, "description": "", "examples": []})
    )
    version, diags = await flows.publish(row.id, registry=get_registry())
    assert version is None
    assert has_errors(diags)
    assert await flows.versions(row.id) == []  # nothing snapshotted


async def test_publish_carries_compile_diagnostics(flows: FlowService) -> None:
    from langgraph_agent_builder.schema.diagnostics import Diagnostic

    row = await flows.create(_spec("blk2"))
    upstream = [Diagnostic.make(DiagnosticCode.E001, "boom")]
    version, diags = await flows.publish(
        row.id, registry=get_registry(), compile_diagnostics=upstream
    )
    assert version is None
    assert any(d.code == DiagnosticCode.E001 for d in diags)


# --------------------------------------------------------------------- rollback / serve
async def test_get_version_and_rollback(flows: FlowService) -> None:
    row = await flows.create(_spec("rb", description="v1"))
    await flows.publish(row.id, registry=get_registry(), bump="minor")
    # mutate the draft, then roll back to the published snapshot
    await flows.update(row.id, _spec("rb", description="v2"))
    rolled = await flows.rollback(row.id, "0.1.0")
    assert rolled is not None
    assert rolled.description == "v1"
    assert await flows.rollback(row.id, "9.9.9") is None
    assert await flows.get_version(row.id, "9.9.9") is None


async def test_serve_version_pinned_vs_latest(flows: FlowService) -> None:
    row = await flows.create(_spec("sv"))
    await flows.publish(row.id, registry=get_registry(), bump="minor")  # 0.1.0
    await flows.publish(row.id, registry=get_registry(), bump="minor")  # 0.2.0
    flow = await flows.get(row.id)
    assert flow is not None
    # default 'latest_published' → newest
    newest = await flows.serve_version(flow)
    assert newest is not None
    assert newest.semver == "0.2.0"
    await flows.set_serve_version(row.id, "0.1.0")
    flow = await flows.get(row.id)
    assert flow is not None
    pinned = await flows.serve_version(flow)
    assert pinned is not None
    assert pinned.semver == "0.1.0"


async def test_serve_version_none_when_unpublished(flows: FlowService) -> None:
    row = await flows.create(_spec("np"))
    flow = await flows.get(row.id)
    assert flow is not None
    assert await flows.serve_version(flow) is None
    assert await flows.latest_version(row.id) is None


async def test_published_flows_filters_by_serving_surface(flows: FlowService) -> None:
    # a2a-enabled + published → included
    served = await flows.create(
        _spec("served", a2a={"enabled": True, "description": "d", "examples": ["x"]})
    )
    await flows.publish(served.id, registry=get_registry(), bump="minor")
    # published but neither a2a nor mcp → excluded
    plain = await flows.create(_spec("plain"))
    await flows.publish(plain.id, registry=get_registry(), bump="minor")
    # unpublished a2a flow → excluded (no version)
    await flows.create(_spec("draft", a2a={"enabled": True, "description": "d", "examples": ["x"]}))

    slugs = {flow.slug for flow, _v, _s in await flows.published_flows()}
    assert slugs == {"served"}
