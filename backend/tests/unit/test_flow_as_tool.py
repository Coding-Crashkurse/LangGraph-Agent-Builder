"""Unit tests for langgraph_agent_builder.components.tools.flow_as_tool.

Uses an in-repo fake AppServices wired through the process service locator; the
LazyToolset factory and the child-run callable are exercised end to end.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from langgraph_agent_builder.components.tools.flow_as_tool import FlowAsTool
from langgraph_agent_builder.sdk.testing import ComponentTestHarness
from langgraph_agent_builder.services import locator

# --------------------------------------------------------------------------- fakes


@dataclass
class _FakeResult:
    status: str
    result_text: str = ""
    error_message: str = ""


@dataclass
class _FakeFlow:
    name: str = "My Flow"
    description: str = "does things"


class _FakeVersion:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.flowspec = spec


class _FakeFlows:
    def __init__(self, flow: _FakeFlow | None, version: _FakeVersion | None) -> None:
        self._flow = flow
        self._version = version

    async def get_by_slug(self, slug: str) -> _FakeFlow | None:
        return self._flow

    async def serve_version(self, flow: _FakeFlow) -> _FakeVersion | None:
        return self._version


class _FakeOrchestrator:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.inputs: list[str] = []

    async def start_run(
        self,
        *,
        spec: dict[str, Any],
        flow_row: _FakeFlow,
        mode: str,
        input_text: str,
        background: bool,
    ) -> tuple[str, str, _FakeResult]:
        self.inputs.append(input_text)
        return ("run-1", "thread-1", self._result)


@dataclass
class _FakeServices:
    flows: _FakeFlows
    orchestrator: _FakeOrchestrator = field(
        default_factory=lambda: _FakeOrchestrator(_FakeResult("completed"))
    )


@pytest.fixture
def restore_locator() -> Iterator[None]:
    prev = locator.get_services()
    try:
        yield
    finally:
        locator.set_services(prev)


def _ctx(config: dict[str, Any]) -> Any:
    return ComponentTestHarness().build(FlowAsTool, config=config).ctx


# --------------------------------------------------------------------------- tests


async def test_flow_as_tool_builds_tooldef(restore_locator: None) -> None:
    orch = _FakeOrchestrator(_FakeResult("completed", result_text="hi there"))
    services = _FakeServices(_FakeFlows(_FakeFlow(description="greets"), _FakeVersion({})), orch)
    locator.set_services(services)

    lazy = FlowAsTool().provide_tools(_ctx({"flow_slug": "my-greeter"}))
    tools = await lazy.resolve()

    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "my_greeter"  # dashes → underscores
    assert tool.description == "greets"
    assert tool.args_schema["required"] == ["message"]
    assert tool.args_schema["properties"]["message"]["type"] == "string"

    result = await tool.callable_ref("hello")
    assert result == "hi there"
    assert orch.inputs == ["hello"]


async def test_flow_as_tool_explicit_name_and_description(restore_locator: None) -> None:
    services = _FakeServices(_FakeFlows(_FakeFlow(), _FakeVersion({})))
    locator.set_services(services)

    lazy = FlowAsTool().provide_tools(
        _ctx({"flow_slug": "x", "tool_name": "greet", "tool_description": "custom desc"})
    )
    tool = (await lazy.resolve())[0]
    assert tool.name == "greet"
    assert tool.description == "custom desc"


async def test_flow_as_tool_description_falls_back_to_flow_name(restore_locator: None) -> None:
    flow = _FakeFlow(name="Greeter", description="")
    services = _FakeServices(_FakeFlows(flow, _FakeVersion({})))
    locator.set_services(services)

    lazy = FlowAsTool().provide_tools(_ctx({"flow_slug": "greeter"}))
    tool = (await lazy.resolve())[0]
    assert tool.description == "Greeter"


async def test_flow_as_tool_missing_flow_raises(restore_locator: None) -> None:
    services = _FakeServices(_FakeFlows(None, None))
    locator.set_services(services)

    lazy = FlowAsTool().provide_tools(_ctx({"flow_slug": "ghost"}))
    with pytest.raises(RuntimeError, match="not found"):
        await lazy.resolve()


async def test_flow_as_tool_unpublished_flow_raises(restore_locator: None) -> None:
    services = _FakeServices(_FakeFlows(_FakeFlow(), None))
    locator.set_services(services)

    lazy = FlowAsTool().provide_tools(_ctx({"flow_slug": "draft"}))
    with pytest.raises(RuntimeError, match="no published version"):
        await lazy.resolve()


async def test_flow_as_tool_child_failure_raises(restore_locator: None) -> None:
    orch = _FakeOrchestrator(_FakeResult("failed", error_message="boom"))
    services = _FakeServices(_FakeFlows(_FakeFlow(), _FakeVersion({})), orch)
    locator.set_services(services)

    lazy = FlowAsTool().provide_tools(_ctx({"flow_slug": "x"}))
    tool = (await lazy.resolve())[0]
    with pytest.raises(RuntimeError, match="ended failed: boom"):
        await tool.callable_ref("go")


async def test_flow_as_tool_without_server_raises(restore_locator: None) -> None:
    locator.set_services(None)
    lazy = FlowAsTool().provide_tools(_ctx({"flow_slug": "x"}))
    with pytest.raises(RuntimeError, match="requires a running lab server"):
        await lazy.resolve()


async def test_flow_as_tool_node_is_noop() -> None:
    node = ComponentTestHarness().build(FlowAsTool, config={"flow_slug": "x"})
    assert await node() == {}
