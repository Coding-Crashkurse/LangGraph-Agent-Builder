"""Palette v2 (33 → 13): the merged/resource-backed nodes + the palette shape.

Covers the five new product components — ``lab.llm.call`` / ``lab.llm.agent``
(model provider resources), ``lab.flow.router`` / ``lab.flow.loop`` (mode
switches), ``lab.rag.kb_retriever`` (knowledge base resource) — plus an assertion
that the non-legacy product palette is exactly the target set and that every
retired/merged id has dropped out of it. Model/KB resolution is exercised with
``fake``/``echo`` providers and a local vector store, so nothing hits the network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from langgraph_agent_builder.components.flow_control.loop import Loop
from langgraph_agent_builder.components.flow_control.router import Router
from langgraph_agent_builder.components.llm.agent import Agent
from langgraph_agent_builder.components.llm.call import Call
from langgraph_agent_builder.components.rag.components import VectorWriter
from langgraph_agent_builder.components.rag.kb_retriever import KbRetriever
from langgraph_agent_builder.sdk.component import (
    BuildContext,
    Component,
    InputBinding,
    NodeKind,
    SecretsResolver,
)
from langgraph_agent_builder.sdk.ports import Document, Message, ResourceHandle, ToolDef
from langgraph_agent_builder.sdk.registry import get_registry
from langgraph_agent_builder.sdk.testing import BuiltNode, ComponentTestHarness

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from langgraph_agent_builder.services.settings import Settings

# The product nodes that must remain in the palette after the cut (lab.flow.code
# is a later phase). Assert the SET, not just the count. lab.data.prompt_template
# ("Prompt") was restored to the palette (Langflow-parity: compose a prompt from a
# template whose {variables} become input ports — the RAG documents→{context} path).
TARGET_PALETTE = {
    "lab.io.start",
    "lab.io.end",
    "lab.io.set_data",
    "lab.data.prompt_template",
    "lab.llm.call",
    "lab.llm.agent",
    "lab.flow.router",
    "lab.flow.loop",
    "lab.flow.human_approval",
    "lab.flow.human_input",
    "lab.rag.kb_retriever",
    "lab.tools.http_request",
    "lab.tools.flow_as_tool",
}

# Ids that were merged/retired — none may appear in the palette anymore.
RETIRED_IDS = {
    "lab.llm.llm_call",
    "lab.llm.llm_agent",
    "lab.flow.llm_router",
    "lab.flow.rule_router",
    "lab.flow.loop_until",
    "lab.data.for_each",
    "lab.rag.retriever",
    "lab.llm.language_model",
    "lab.llm.structured_output",
    "lab.io.text_input",
    "lab.io.text_output",
    "lab.tools.calculator",
}


# --------------------------------------------------------------------- fakes/infra
class _FakeResources:
    """Stand-in for ResourcesService.resolved_config keyed by (rtype, name)."""

    def __init__(self, configs: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._configs = configs

    async def resolved_config(self, rtype: str, name: str) -> dict[str, Any] | None:
        return self._configs.get((rtype, name))


class _FakeSvc:
    def __init__(self, resources: _FakeResources, vectorstores: Any = None) -> None:
        self.resources = resources
        self.vectorstores = vectorstores


@pytest.fixture
def restore_locator() -> Iterator[None]:
    """Save/restore the process-wide service locator around a test."""
    from langgraph_agent_builder.services import locator

    saved = locator.get_services()
    try:
        yield
    finally:
        locator.set_services(saved)


def _set_model_provider(name: str, config: dict[str, Any]) -> None:
    from langgraph_agent_builder.services import locator

    locator.set_services(_FakeSvc(_FakeResources({("model_provider", name): config})))


def _model_ref(name: str, **payload: Any) -> ResourceHandle:
    return ResourceHandle(name=name, resource_type="model_provider", payload=payload)


def _build_with_settings(
    component: type[Component],
    settings: Settings | None = None,
    config: dict[str, Any] | None = None,
    port_values: dict[str, Any] | None = None,
    node_id: str = "under_test",
) -> BuiltNode:
    bindings = {
        name: InputBinding(input_name=name, channel=None, constant=value)
        for name, value in (port_values or {}).items()
    }
    ctx = BuildContext(
        node_id=node_id,
        flow_id="test-flow",
        label=component.display_name or node_id,
        config=dict(config or {}),
        secrets=SecretsResolver({}),
        input_bindings=bindings,
        settings=settings,
    )
    return BuiltNode(component().build(ctx), ctx)


# --------------------------------------------------------------------- palette shape
def test_product_palette_is_exactly_the_target_set() -> None:
    reg = get_registry()
    product = {c.component_id for c in reg.all() if not c.legacy and c.category != "testing"}
    assert product == TARGET_PALETTE


def _get(cid: str) -> type[Component]:
    cls = get_registry().get(cid)
    assert cls is not None, f"{cid} must stay loadable"
    return cls


def test_retired_ids_absent_from_palette_but_still_loadable() -> None:
    palette = {c.component_id for c in get_registry().all() if not c.legacy}
    for cid in RETIRED_IDS:
        assert cid not in palette, f"{cid} should be legacy"
        assert _get(cid).legacy is True


def test_merged_nodes_advertise_successors() -> None:
    assert _get("lab.llm.llm_call").successor == "lab.llm.call"
    assert _get("lab.llm.llm_agent").successor == "lab.llm.agent"
    assert _get("lab.flow.llm_router").successor == "lab.flow.router"
    assert _get("lab.flow.rule_router").successor == "lab.flow.router"
    assert _get("lab.flow.loop_until").successor == "lab.flow.loop"
    assert _get("lab.data.for_each").successor == "lab.flow.loop"
    assert _get("lab.rag.retriever").successor == "lab.rag.kb_retriever"
    assert _get("lab.rag.pgvector_retriever").successor == "lab.rag.kb_retriever"


# --------------------------------------------------------------------- lab.llm.call
async def test_call_resolves_model_provider_resource_and_streams(
    restore_locator: None,
) -> None:
    _set_model_provider("echoprov", {"provider": "echo"})
    built = ComponentTestHarness().build(
        Call,
        config={"prompt": "Say {greeting}", "model": _model_ref("echoprov")},
        ports={"greeting": "hello"},
    )
    result = await built()
    assert result["text"] == "Say hello"
    assert isinstance(result["message"], Message)
    assert result["message"].role == "assistant"


async def test_call_structured_output_via_headless_inline_provider() -> None:
    # No service context: the handle payload carries an inline fake provider,
    # so the node stays runnable headless (python export / offline tests).
    from langgraph_agent_builder.services import locator

    saved = locator.get_services()
    locator.set_services(None)
    try:
        built = ComponentTestHarness().build(
            Call,
            config={
                "prompt": "extract",
                "model": _model_ref("p", provider="fake", replies=['{"a": 7}']),
                "stream_tokens": False,
                "structured_output": True,
                "output_schema": {"type": "object"},
            },
        )
        result = await built()
        assert result["text"] == '{"a": 7}'
        assert result["json"] == {"a": 7}
    finally:
        locator.set_services(saved)


async def test_call_headless_without_provider_raises() -> None:
    from langgraph_agent_builder.errors import LabRuntimeError
    from langgraph_agent_builder.services import locator

    saved = locator.get_services()
    locator.set_services(None)
    try:
        built = ComponentTestHarness().build(
            Call, config={"prompt": "hi", "model": _model_ref("ghost")}
        )
        with pytest.raises(LabRuntimeError, match="could not be resolved"):
            await built()
    finally:
        locator.set_services(saved)


# --------------------------------------------------------------------- lab.llm.agent
async def test_agent_resolves_resource_and_echoes(restore_locator: None) -> None:
    _set_model_provider("echoprov", {"provider": "echo"})
    built = ComponentTestHarness().build(Agent, config={"model": _model_ref("echoprov")})
    result = await built(state={"messages": [HumanMessage(content="hello agent")]})
    assert isinstance(result["message"], Message)
    assert result["message"].content == "hello agent"


async def test_agent_tools_attached_but_model_cannot_bind(restore_locator: None) -> None:
    _set_model_provider("fakeprov", {"provider": "fake", "replies": ["answer without tools"]})
    tool = StructuredTool.from_function(
        func=lambda text: text, name="echo_tool", description="Echo."
    )
    built = ComponentTestHarness().build(
        Agent,
        config={"model": _model_ref("fakeprov")},
        tools=[ToolDef(name="echo_tool", description="Echo", callable_ref=tool)],
    )
    result = await built(state={"messages": [HumanMessage(content="hi")]})
    assert result["message"].content == "answer without tools"


# --------------------------------------------------------------------- lab.flow.router
def test_router_outputs_switch_by_mode() -> None:
    rules = Router.outputs_for_config(
        {"mode": "rules", "rules": [{"label": "a"}, {"label": "a"}], "default_label": "fallback"}
    )
    assert [o.name for o in rules] == ["a", "fallback"]
    llm = Router.outputs_for_config({"mode": "llm", "labels": ["refund", "other"]})
    assert [o.name for o in llm] == ["refund", "other"]
    assert Router.node_kind is NodeKind.ROUTER


async def test_router_rules_mode_routes_first_match() -> None:
    built = ComponentTestHarness().build(
        Router,
        config={
            "mode": "rules",
            "rules": [{"label": "refund", "when": '"refund" in message'}],
            "default_label": "default",
        },
    )
    assert (await built({"messages": [HumanMessage(content="refund please")]}))["route"] == "refund"
    assert (await built({"messages": [HumanMessage(content="hello")]}))["route"] == "default"


async def test_router_llm_mode_keyword_fallback() -> None:
    # no model wired → deterministic keyword matching (reuses LLMRouter logic)
    built = ComponentTestHarness().build(
        Router, config={"mode": "llm", "labels": ["refund", "other"]}
    )
    assert (await built({"messages": [HumanMessage(content="I want a refund")]}))[
        "route"
    ] == "refund"


# --------------------------------------------------------------------- lab.flow.loop
def test_loop_kind_and_outputs_switch_by_mode() -> None:
    assert Loop.node_kind_for_config({"mode": "collection"}) is NodeKind.TASK
    assert Loop.node_kind_for_config({"mode": "until"}) is NodeKind.ROUTER
    assert [o.name for o in Loop.outputs_for_config({"mode": "collection"})] == ["results", "text"]
    assert [o.name for o in Loop.outputs_for_config({"mode": "until"})] == ["continue", "done"]


async def test_loop_collection_maps_template() -> None:
    built = ComponentTestHarness().build(
        Loop,
        config={"mode": "collection", "template": "n={{ item }}", "separator": ","},
        ports={"items": [1, 2, 3]},
    )
    result = await built()
    assert result["text"] == "n=1,n=2,n=3"
    assert [r["result"] for r in result["results"]] == ["n=1", "n=2", "n=3"]


async def test_loop_until_counts_and_stops() -> None:
    built = ComponentTestHarness().build(Loop, config={"mode": "until", "max_iterations": 3})
    first = await built()
    assert first["route"] == "continue"
    assert first["data"] == {"__loop_under_test": 1}
    done = await built({"data": {"__loop_under_test": 3}})
    assert done["route"] == "done"


# --------------------------------------------------------------------- lab.rag.kb_retriever
async def test_kb_retriever_searches_referenced_knowledge_base(
    sqlite_settings: Settings, restore_locator: None
) -> None:
    from langgraph_agent_builder.services import locator

    # 1. ingest into a local collection (headless local provider under tmp home)
    locator.set_services(None)
    writer = _build_with_settings(
        VectorWriter,
        sqlite_settings,
        config={"vector_store": {"$vectorstore": "local", "collection": "kb"}},
        port_values={
            "documents": [
                {"page_content": "the cat sat on the mat", "metadata": {"source": "a"}},
                {"page_content": "dogs are loyal companions", "metadata": {"source": "b"}},
            ],
            "embedding": {"provider": "fake", "dim": 32},
        },
    )
    await writer()

    # 2. a knowledge_base resource points at that connection/collection/embedding
    kb_cfg = {
        "vectorstore": "local",
        "collection": "kb",
        "embedding": {"provider": "fake", "dim": 32},
    }
    locator.set_services(_FakeSvc(_FakeResources({("knowledge_base", "kb"): kb_cfg})))
    retriever = _build_with_settings(
        KbRetriever,
        sqlite_settings,
        config={
            "knowledge_base": ResourceHandle(name="kb", resource_type="knowledge_base"),
            "query": "cat",
            "k": 5,
        },
    )
    docs = (await retriever())["documents"]
    assert {d.page_content for d in docs} == {
        "the cat sat on the mat",
        "dogs are loyal companions",
    }
    assert all(isinstance(d, Document) for d in docs)


# --------------------------------------------------------------------- resolved_config (new method)
SqliteStack = tuple["Settings", "async_sessionmaker[AsyncSession]"]


async def test_resolved_config_resolves_secret_refs(sqlite_stack: SqliteStack) -> None:
    from langgraph_agent_builder.services.mcp_servers import McpServersService
    from langgraph_agent_builder.services.resources import ResourcesService
    from langgraph_agent_builder.services.secrets import SecretsService
    from langgraph_agent_builder.services.vectorstores import VectorStoreService

    settings, sessions = sqlite_stack
    secrets = SecretsService(settings, sessions)
    res = ResourcesService(
        settings,
        sessions,
        secrets,
        McpServersService(sessions),
        VectorStoreService(settings, sessions, secrets),
    )
    await secrets.set("K", "sk-live", kind="credential")
    await res.upsert("model_provider", "p", {"provider": "openai", "api_key": {"$secret": "K"}})
    cfg = await res.resolved_config("model_provider", "p")
    assert cfg == {"provider": "openai", "api_key": "sk-live"}
    # absent resource → None
    assert await res.resolved_config("model_provider", "missing") is None
