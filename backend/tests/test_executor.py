"""Executor integration: run/stream/interrupt/resume/cancel/RT codes (SPEC §15)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from langgraph_agent_builder.compiler import compile_flow
from langgraph_agent_builder.runtime.executor import Executor
from langgraph_agent_builder.runtime.streams import EventBus
from langgraph_agent_builder.schema.events import RunEvent
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
    assert result.result_text == "Hello from LAB!"
    names = [e.event for e in seen]
    assert names[0] == "run_started"
    assert names[-1] == "run_finished"
    assert "node_started" in names
    assert "node_finished" in names
    assert "fake.thinking" in names  # custom component event


async def test_table_terminal_emits_structured_result(
    mem_executor: tuple[Executor, EventBus],
) -> None:
    """A Table (list) terminal populates result_json as {"rows": [...]} (SPEC §8.1).

    Regression guard: extract_result's terminal branch must wrap a list the same
    way as its until_node branch, so MCP structuredContent / A2A DataParts are
    emitted for Table outputs — not only for Json (dict) ones.
    """
    executor, _bus = mem_executor
    spec = {
        "schema_version": "1",
        "flow": {"name": "tbl", "slug": "tbl", "description": "table flow"},
        "nodes": [
            {
                "id": "start",
                "component_id": "lab.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "fe",
                "component_id": "lab.data.for_each",
                "component_version": "1.0.0",
                "config": {"template": "{{ item }}!"},
                "position": {"x": 300, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lab.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 600, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "fe", "input": "items"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "fe", "output": "results"},
                "target": {"node": "end", "input": "table"},
            },
        ],
    }
    compiled = compile_flow(spec, use_cache=False)
    result = await executor.execute(compiled, input_text="hi")
    assert result.status == "completed"
    assert result.result_json == {"rows": [{"index": 0, "result": "hi!"}]}
    assert '"result": "hi!"' in result.result_text  # text carries the JSON dump


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


async def test_pending_interrupt_public_accessor(
    mem_executor: tuple[Executor, EventBus],
) -> None:
    """pending_interrupt drives the resume-vs-new-run decision (SPEC §7.7):
    None on a fresh thread, the payload while parked, None again after resume."""
    executor, _bus = mem_executor
    compiled = compile_flow(approval_spec(), use_cache=False)
    assert await executor.pending_interrupt(compiled, "t-pending") is None

    result = await executor.execute(compiled, input_text="draft", thread_id="t-pending")
    assert result.status == "input_required"
    pending = await executor.pending_interrupt(compiled, "t-pending")
    assert pending is not None
    assert pending["kind"] == "approval"
    assert pending["prompt"] == "Release this answer?"

    resumed = await executor.execute(
        compiled, thread_id="t-pending", resume={"decision": "approve"}
    )
    assert resumed.status == "completed"
    assert await executor.pending_interrupt(compiled, "t-pending") is None


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
        "component_id": "lab.testing.failing_node",
        "component_version": "1.0.0",
        "config": {"error_message": "boom"},
        "position": {"x": 0, "y": 0},
    }
    compiled = compile_flow(spec, use_cache=False)
    seen: list[RunEvent] = []

    async def sink(event: RunEvent) -> None:
        seen.append(event)

    result = await executor.execute(compiled, input_text="x", event_sink=sink)
    assert result.status == "failed"
    assert result.error_code == "RT103"
    assert "boom" in (result.error_message or "")
    assert result.node_id == "fake"  # §5.6: every RT error carries node_id
    finished = [e for e in seen if e.event == "run_finished"]
    assert [e.data["node_id"] for e in finished] == ["fake"]
    # exactly one node_error: the wrapper's, not a duplicate from the executor
    assert [e.event for e in seen].count("node_error") == 1


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
                "component_id": "lab.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "fake",
                "component_id": "lab.testing.fake_llm",
                "component_version": "1.0.0",
                "config": {"replies": ["again"]},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "loop",
                "component_id": "lab.flow.loop_until",
                "component_version": "1.0.0",
                "config": {"max_iterations": 100},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lab.io.end",
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
                "component_id": "lab.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "fake",
                "component_id": "lab.testing.fake_llm",
                "component_version": "1.0.0",
                "config": {"replies": ["draft", "draft", "APPROVED final"]},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "loop",
                "component_id": "lab.flow.loop_until",
                "component_version": "1.0.0",
                "config": {"condition": '"APPROVED" in message', "max_iterations": 10},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lab.io.end",
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
    from langgraph_agent_builder.sdk import BuildContext, Component, NodeKind, Output, ports
    from langgraph_agent_builder.sdk import fields as sdk_fields
    from langgraph_agent_builder.sdk.component import NodeFn
    from langgraph_agent_builder.sdk.registry import ComponentRegistry, get_registry

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
                "component_id": "lab.io.start",
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
                "component_id": "lab.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end2",
                "component_id": "lab.io.text_output",
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
    seen: list[RunEvent] = []

    async def sink(event: RunEvent) -> None:
        seen.append(event)

    result = await executor.execute(compiled, input_text="x", event_sink=sink)
    assert result.status == "failed"
    assert result.error_code == "RT102"
    assert result.node_id == "r"
    # the node wrapper emits node_error only for RT103; the executor must fill
    # the gap so every RT error reaches the event stream (SPEC §5.6)
    assert any(e.event == "node_error" and e.data["code"] == "RT102" for e in seen)


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
    assert "".join(tokens) == "Hello from LAB!"


async def test_event_bus_replay_and_live() -> None:
    """A late subscriber replays a finished run's persisted events and the
    replayed terminal event ends the stream (SPEC §6.2 Last-Event-ID)."""
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()

    async def get() -> InMemorySaver:
        return saver

    stored: list[RunEvent] = []

    async def persist(event: RunEvent) -> None:
        stored.append(event)

    async def load(run_id: str, after_seq: int) -> list[RunEvent]:
        return [e for e in stored if e.run_id == run_id and e.seq > after_seq]

    bus = EventBus(persist=persist, load=load)
    executor = Executor(checkpointer_getter=get, bus=bus)
    compiled = compile_flow(hello_spec(), use_cache=False)
    result = await executor.execute(compiled, input_text="hi")
    assert result.status == "completed"
    await bus.drain()

    async def collect() -> list[RunEvent]:
        return [e async for e in bus.subscribe(result.run_id, replay=True)]

    replayed = await asyncio.wait_for(collect(), timeout=5)
    names = [e.event for e in replayed]
    assert names[0] == "run_started"
    assert names[-1] == "run_finished"
    seqs = [e.seq for e in replayed]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)  # monotonic, no duplicates dropped


async def test_rt101_data_write_conflict(mem_executor: tuple[Executor, EventBus]) -> None:
    """Two nodes writing the same data key in one superstep → RT101 (SPEC §5.1/§5.6)."""
    from langgraph_agent_builder.sdk import BuildContext, Component, NodeKind, Output, ports
    from langgraph_agent_builder.sdk import fields as sdk_fields
    from langgraph_agent_builder.sdk.component import NodeFn
    from langgraph_agent_builder.sdk.registry import ComponentRegistry, get_registry

    class DataWriter(Component):
        component_id = "test.data.conflict_writer"
        display_name = "Data Writer"
        description = "writes a shared data key"
        category = "testing"
        node_kind = NodeKind.TASK
        inputs = [sdk_fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE)]
        outputs = [Output(name="out", port=ports.MESSAGE)]

        def build(self, ctx: BuildContext) -> NodeFn:
            async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
                return {"out": "written", "data": {"shared": "value"}}

            return node

    registry = ComponentRegistry()
    for cls in get_registry().components.values():
        registry.register(cls, "test")
    registry.register(DataWriter, "test")

    spec = {
        "schema_version": "1",
        "flow": {"name": "conflict", "slug": "conflict", "description": "x"},
        "nodes": [
            {
                "id": "start",
                "component_id": "lab.io.start",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "w1",
                "component_id": "test.data.conflict_writer",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "w2",
                "component_id": "test.data.conflict_writer",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end",
                "component_id": "lab.io.end",
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "end2",
                "component_id": "lab.io.text_output",
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
                "target": {"node": "w1", "input": "input"},
            },
            {
                "id": "e2",
                "kind": "data",
                "source": {"node": "start", "output": "message"},
                "target": {"node": "w2", "input": "input"},
            },
            {
                "id": "e3",
                "kind": "data",
                "source": {"node": "w1", "output": "out"},
                "target": {"node": "end", "input": "message"},
            },
            {
                "id": "e4",
                "kind": "data",
                "source": {"node": "w2", "output": "out"},
                "target": {"node": "end2", "input": "text"},
            },
        ],
    }
    executor, _bus = mem_executor
    compiled = compile_flow(spec, registry=registry, use_cache=False)
    assert compiled.ok, [d.message for d in compiled.diagnostics]
    seen: list[RunEvent] = []

    async def sink(event: RunEvent) -> None:
        seen.append(event)

    result = await executor.execute(compiled, input_text="x", event_sink=sink)
    assert result.status == "failed"
    assert result.error_code == "RT101"
    assert result.node_id in ("w1", "w2")  # §5.6: every RT error carries node_id
    errors = [e for e in seen if e.event == "node_error"]
    assert [e.data["code"] for e in errors] == ["RT101"]
    finished = [e for e in seen if e.event == "run_finished"]
    assert [e.data["node_id"] for e in finished] == [result.node_id]


async def test_debug_step_and_continue(mem_executor: tuple[Executor, EventBus]) -> None:
    """Debug mode pauses before every node; step re-pauses, continue finishes (§6.1)."""
    executor, _bus = mem_executor
    compiled = compile_flow(hello_spec(), use_cache=False)

    first = await executor.execute(compiled, input_text="hi", thread_id="dbg1", debug=True)
    assert first.status == "input_required"
    assert first.interrupt is not None
    assert first.interrupt["kind"] == "debug_step"
    assert first.interrupt_node == "start"

    stepped = await executor.execute(compiled, thread_id="dbg1", debug_action="step")
    assert stepped.status == "input_required"
    assert stepped.interrupt is not None
    assert stepped.interrupt["kind"] == "debug_step"
    assert stepped.interrupt_node == "fake"

    done = await executor.execute(compiled, thread_id="dbg1", debug_action="continue")
    assert done.status == "completed"
    assert done.result_text == "Hello from LAB!"


async def test_cancel_writes_status_before_run_cancelled_event() -> None:
    """Terminal ordering (SPEC §6.2): the run row must hold 'cancelled' before
    run_cancelled reaches subscribers — they re-read the row at stream end."""
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()

    async def get() -> InMemorySaver:
        return saver

    timeline: list[str] = []

    class RecordingBus(EventBus):
        def publish(self, event: RunEvent) -> RunEvent:
            timeline.append(f"event:{event.event}")
            return super().publish(event)

        def close_run(self, run_id: str) -> None:
            timeline.append("close_run")
            super().close_run(run_id)

    async def on_status(run_id: str, status: str, **kw: Any) -> None:
        timeline.append(f"status:{status}")

    executor = Executor(checkpointer_getter=get, bus=RecordingBus(), on_status=on_status)
    compiled = compile_flow(slow_spec(seconds=30), use_cache=False)
    handle = executor.start(compiled, input_text="zzz")
    await asyncio.sleep(0.3)
    assert await executor.cancel(handle.run_id)
    await asyncio.wait_for(handle.done.wait(), timeout=5)

    assert timeline.index("status:cancelled") < timeline.index("event:run_cancelled")
    assert timeline.index("event:run_cancelled") < timeline.index("close_run")


async def test_unexpected_exception_fails_run_and_closes_stream() -> None:
    """Catch-all (SPEC §5.6): an unexpected crash still writes a failed status,
    emits run_finished and closes the bus — no zombie 'running' runs."""

    async def broken() -> Any:
        raise ConnectionError("db down")

    statuses: list[str] = []

    async def on_status(run_id: str, status: str, **kw: Any) -> None:
        statuses.append(status)

    closed: list[str] = []

    class RecordingBus(EventBus):
        def close_run(self, run_id: str) -> None:
            closed.append(run_id)
            super().close_run(run_id)

    executor = Executor(checkpointer_getter=broken, bus=RecordingBus(), on_status=on_status)
    compiled = compile_flow(hello_spec(), use_cache=False)
    seen: list[RunEvent] = []

    async def sink(event: RunEvent) -> None:
        seen.append(event)

    result = await executor.execute(compiled, input_text="hi", event_sink=sink)
    assert result.status == "failed"
    assert result.error_code == "RT103"
    assert "db down" in (result.error_message or "")
    assert statuses[-1] == "failed"
    assert seen[-1].event == "run_finished"
    assert seen[-1].data["error_code"] == "RT103"
    assert closed == [result.run_id]


async def test_harness_run_in_flow() -> None:
    from langgraph_agent_builder.components.testing.fake_llm import FakeLLM
    from langgraph_agent_builder.sdk.testing import ComponentTestHarness

    harness = ComponentTestHarness()
    outcome = await harness.run_in_flow(FakeLLM, config={"replies": ["harnessed"]})
    assert outcome["status"] == "completed"
    assert outcome["result_text"] == "harnessed"


async def test_harness_build() -> None:
    from langgraph_agent_builder.components.tools.basic_tools import Calculator
    from langgraph_agent_builder.sdk.testing import ComponentTestHarness

    node = ComponentTestHarness().build(Calculator, config={"expression": "(2+3)*4"})
    result = await node()
    assert result["text"] == "20"
