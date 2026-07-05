import asyncio
import sys

import httpx
import pytest
from a2a.client import ClientConfig, ClientFactory
from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver

from graphforge.compiler.spec import FlowSpec
from graphforge.components.registry import registry
from graphforge.runtime.events import EventBus
from graphforge.runtime.manager import FlowRuntimeManager
from graphforge.runtime.runs import RunLog
from graphforge.settings import Settings


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        testing=True,
        base_url="http://test",
        database_url="postgresql+asyncpg://unused:unused@localhost:1/unused",
    )


@pytest.fixture
def loaded_registry():
    registry.load(include_testing=True)
    return registry


class PublishedApp:
    def __init__(self, app: FastAPI, manager: FlowRuntimeManager, bus: EventBus) -> None:
        self.app = app
        self.manager = manager
        self.bus = bus

    def httpx_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://test",
            timeout=30.0,
        )

    def a2a_client(self, flow_id: str, httpx_client: httpx.AsyncClient, *, streaming: bool):
        mounted = self.manager.mounted(flow_id)
        assert mounted is not None and mounted.card is not None
        factory = ClientFactory(ClientConfig(streaming=streaming, httpx_client=httpx_client))
        return factory.create(mounted.card)


@pytest.fixture
def publish_app(settings, loaded_registry):
    """Factory: mount a FlowSpec as a published A2A app with in-memory infra."""
    managers: list[FlowRuntimeManager] = []

    async def _publish(spec: FlowSpec) -> PublishedApp:
        app = FastAPI()
        bus = EventBus()
        manager = FlowRuntimeManager(
            app,
            settings=settings,
            registry=loaded_registry,
            bus=bus,
            task_store=InMemoryTaskStore(),
            checkpointer=InMemorySaver(),
            run_log=RunLog(None),
        )
        await manager.publish_flow(spec)
        managers.append(manager)
        return PublishedApp(app, manager, bus)

    yield _publish


def simple_flow(slug: str = "simple", replies: list[str] | None = None) -> FlowSpec:
    return FlowSpec(
        slug=slug,
        name="Simple",
        nodes=[
            {
                "id": "llm",
                "component": "fake_llm",
                "config": {"replies": replies or ["hello from fake"]},
            }
        ],
        edges=[
            {"kind": "control", "source": "__start__", "target": "llm"},
            {"kind": "control", "source": "llm", "target": "__end__"},
        ],
    )


def hitl_flow(slug: str = "hitl") -> FlowSpec:
    return FlowSpec(
        slug=slug,
        name="HITL",
        nodes=[
            {"id": "llm", "component": "fake_llm", "config": {"replies": ["draft answer"]}},
            {"id": "review", "component": "human_approval", "config": {"prompt": "Release?"}},
        ],
        edges=[
            {"kind": "control", "source": "__start__", "target": "llm"},
            {"kind": "control", "source": "llm", "target": "review"},
            {
                "kind": "control",
                "source": "review",
                "source_handle": "approved",
                "target": "__end__",
            },
            {
                "kind": "control",
                "source": "review",
                "source_handle": "rejected",
                "target": "llm",
            },
        ],
    )
