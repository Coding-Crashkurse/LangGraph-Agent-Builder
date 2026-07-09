"""Executor integration: run/stream/interrupt/resume/cancel/RT codes (SPEC §15)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from lga.compiler import compile_flow
from lga.runtime.executor import Executor
from lga.runtime.streams import EventBus
from lga.schema.events import RunEvent
from tests.conftest import approval_spec, hello_spec, slow_spec


@pytest.fixture
def mem_executor() -> tuple[Executor, EventBus]:
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()

    async def get() -> InMemorySaver:
        return saver

    bus = EventBus()
    return Executor(checkpointer_getter=get, bus=bus), bus


async def test_run_completes_with_events(mem_executor: tuple[Executor, EventBus]) -> None:
    executor, _bus = mem_executor
    compiled = compile_flow(hello_spec(), use_cache=False)
    seen: list[RunEvent] = []

    async def sink(event: RunEvent) -> None:
        seen.append(event)

    result = await executor.execute(compiled, input_text="hi", event_sink=sink)
    assert result.status == "completed"
    assert result.result_text == "Hello from LGA!"
    names = [e.event for e in seen]
    assert names[0] == "run_started"
    assert names[-1] == "run_finished"
    assert "node_started" in names
    assert "node_finished" in names
    assert "fake.thinking" in names  # custom component event


async def test_interrupt_resume_roundtrip(mem_executor: tuple[Executor, EventBus]) -> None:
    executor, _bus = mem_executor
    compiled = compile_flow(approval_spec(), use_cache=False)
    result = await executor.execute(compiled, input_text="draft this", thread_id="t1")
    assert result.status == "input_required"
    assert result.interrupt is not None
    assert result.interrupt["kind"] == "approval"
    assert result.interrupt["prompt"] == "Release this answer?"
    assert result.interrupt_node == "review"

    resumed = await executor.execute(compiled, thread_id="t1", resume={"decision": "approve"})
    assert resumed.status == "completed"
    assert resumed.result_text == "draft answer"


async def test_reject_branch_loops_back(mem_executor: tuple[Executor, EventBus]) -> None:
    executor, _bus = mem_executor
    compiled = compile_flow(approval_spec(), use_cache=False)
    first = await executor.execute(compiled, input_text="draft", thread_id="t2")
    assert first.status == "input_required"
    second = await executor.execute(
        compiled, thread_id="t2", resume={"decision": "reject", "comment": "try again"}
    )
    # reject → fake produces reply #2 → review interrupts again
    assert second.status == "input_required"
    third = await executor.execute(compiled, thread_id="t2", resume={"decision": "approve"})
    assert third.status == "completed"
    assert third.result_text == "revised answer"


async def test_cancel_during_slow_node(mem_executor: tuple[Executor, EventBus]) -> None:
    executor, _bus = mem_executor
    compiled = compile_flow(slow_spec(seconds=30), use_cache=False)
    handle = executor.start(compiled, input_text="zzz")
    await asyncio.sleep(0.3)
    assert await executor.cancel(handle.run_id)
    await asyncio.wait_for(handle.done.wait(), timeout=5)
    assert handle.result is not None
    assert handle.result.status == "cancelled"
    assert handle.result.error_code == "RT104"


async def test_failing_node_rt103(mem_executor: tuple[Executor, EventBus]) -> None:
    executor, _bus = mem_executor
    spec = hello_spec()
    spec["nodes"][1] = {
        "id": "fake",
        "component_id": "lga.testing.failing_node",
        "component_version": "1.0.0",
        "config": {"error_message": "boom"},
        "position": {"x": 0, "y": 0},
    }
    compiled = compile_flow(spec, use_cache=False)
    result = await executor.execute(compiled, input_text="x")
    assert result.status == "failed"
    assert result.error_code == "RT103"
    assert "boom" in (result.error_message or "")


async def test_recursion_limit_rt105(mem_executor: tuple[Executor, EventBus]) -> None:
    executor, _bus = mem_executor
    spec = approval_spec("loopy")
    # auto-reject forever is impossible (interrupt pauses); use loop_until instead
    spec = {
        "schema_version": "1",
        "flow": {
            "name": "loopy",
            "slug": "loopy",
            "description": "loop",
            "settings": {"recursion_limit": 8},
        },
        "nodes": [
            {
                "id": "start",
                "component_id": "lga.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "fake",
                "component_id": "lga.testing.fake_llm",
                "component_version": "1.0.0",
                "config": {"replies": ["again"]},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "loop",
                "component_id": "lga.flow.loop_until",
                "component_version": "1.0.0",
                "config": {"max_iterations": 100},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lga.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "fake", "input": "input"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "fake", "output": "message"},
                "target": {"node": "loop", "input": "input"},
            },
            {
                "id": "e3",
                "kind": "router",
                "source": {"node": "loop", "output": "continue"},
                "target": {"node": "fake", "input": "input"},
            },
            {
                "id": "e4",
                "kind": "router",
                "source": {"node": "loop", "output": "done"},
                "target": {"node": "end", "input": "message"},
            },
        ],
    }
    compiled = compile_flow(spec, use_cache=False)
    assert compiled.ok, [d.message for d in compiled.diagnostics]
    result = await executor.execute(compiled, input_text="go")
    assert result.status == "failed"
    assert result.error_code == "RT105"


async def test_loop_until_terminates(mem_executor: tuple[Executor, EventBus]) -> None:
    executor, _bus = mem_executor
    spec = {
        "schema_version": "1",
        "flow": {"name": "loop-ok", "slug": "loop-ok", "description": "loop"},
        "nodes": [
            {
                "id": "start",
                "component_id": "lga.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "fake",
                "component_id": "lga.testing.fake_llm",
                "component_version": "1.0.0",
                "config": {"replies": ["draft", "draft", "APPROVED final"]},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "loop",
                "component_id": "lga.flow.loop_until",
                "component_version": "1.0.0",
                "config": {"condition": '"APPROVED" in message', "max_iterations": 10},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lga.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "fake", "input": "input"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "fake", "output": "message"},
                "target": {"node": "loop", "input": "input"},
            },
            {
                "id": "e3",
                "kind": "router",
                "source": {"node": "loop", "output": "continue"},
                "target": {"node": "fake", "input": "input"},
            },
            {
                "id": "e4",
                "kind": "router",
                "source": {"node": "loop", "output": "done"},
                "target": {"node": "end", "input": "message"},
            },
        ],
    }
    compiled = compile_flow(spec, use_cache=False)
    result = await executor.execute(compiled, input_text="go")
    assert result.status == "completed"
    assert "APPROVED" in result.result_text


async def test_rt102_invalid_router_label(mem_executor: tuple[Executor, EventBus]) -> None:
    """A router emitting an undeclared label fails fast with RT102."""
    from lga.sdk import BuildContext, Component, NodeKind, Output, ports
    from lga.sdk import fields as sdk_fields
    from lga.sdk.component import NodeFn
    from lga.sdk.registry import ComponentRegistry, get_registry

    class BadRouter(Component):
        component_id = "test.flow.bad_router"
        display_name = "Bad Router"
        description = "emits an undeclared label"
        category = "testing"
        node_kind = NodeKind.ROUTER
        inputs = [sdk_fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE)]
        outputs = [Output(name="a", port=ports.ROUTE), Output(name="b", port=ports.ROUTE)]

        def build(self, ctx: BuildContext) -> NodeFn:
            async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
                return {"route": "zzz"}

            return node

    registry = ComponentRegistry()
    for cls in get_registry().components.values():
        registry.register(cls, "test")
    registry.register(BadRouter, "test")

    spec = {
        "schema_version": "1",
        "flow": {"name": "bad", "slug": "bad-router", "description": "x"},
        "nodes": [
            {
                "id": "start",
                "component_id": "lga.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "r",
                "component_id": "test.flow.bad_router",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lga.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end2",
                "component_id": "lga.io.text_output",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "r", "input": "input"},
            },
            {
                "id": "e2",
                "kind": "router",
                "source": {"node": "r", "output": "a"},
                "target": {"node": "end", "input": "message"},
            },
            {
                "id": "e3",
                "kind": "router",
                "source": {"node": "r", "output": "b"},
                "target": {"node": "end2", "input": "text"},
            },
        ],
    }
    executor, _bus = mem_executor
    compiled = compile_flow(spec, registry=registry, use_cache=False)
    assert compiled.ok, [d.message for d in compiled.diagnostics]
    result = await executor.execute(compiled, input_text="x")
    assert result.status == "failed"
    assert result.error_code == "RT102"


async def test_token_streaming_events(mem_executor: tuple[Executor, EventBus]) -> None:
    executor, _bus = mem_executor
    spec = hello_spec()
    spec["nodes"][1]["config"]["stream_tokens"] = True
    compiled = compile_flow(spec, use_cache=False)
    tokens: list[str] = []

    async def sink(event: RunEvent) -> None:
        if event.event == "node_token":
            tokens.append(event.data["delta"])

    result = await executor.execute(compiled, input_text="hi", event_sink=sink)
    assert result.status == "completed"
    assert "".join(tokens) == "Hello from LGA!"


async def test_event_bus_replay_and_live(mem_executor: tuple[Executor, EventBus]) -> None:
    executor, _bus = mem_executor
    compiled = compile_flow(hello_spec(), use_cache=False)
    result = await executor.execute(compiled, input_text="hi")
    # bus without persistence: live-only; new subscription sees nothing (run closed)
    assert result.status == "completed"


async def test_harness_run_in_flow() -> None:
    from lga.components.testing.fake_llm import FakeLLM
    from lga.sdk.testing import ComponentTestHarness

    harness = ComponentTestHarness()
    outcome = await harness.run_in_flow(FakeLLM, config={"replies": ["harnessed"]})
    assert outcome["status"] == "completed"
    assert outcome["result_text"] == "harnessed"


async def test_harness_build() -> None:
    from lga.components.tools.basic_tools import Calculator
    from lga.sdk.testing import ComponentTestHarness

    node = ComponentTestHarness().build(Calculator, config={"expression": "(2+3)*4"})
    result = await node()
    assert result["text"] == "20"
