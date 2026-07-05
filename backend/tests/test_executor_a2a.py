"""Executor integration tests: real a2a-sdk client against the in-process
mounted A2A app (httpx ASGITransport), in-memory task store + checkpointer."""

import asyncio
from uuid import uuid4

from a2a.types import DataPart, Message, Part, Role, Task, TaskIdParams, TaskState, TextPart

from graphforge.compiler.spec import EdgeSpec, NodeSpec

from .conftest import hitl_flow, simple_flow


def _final_task(events) -> Task:
    tasks = [item[0] for item in events if isinstance(item, tuple)]
    assert tasks, f"no task events in {events!r}"
    return tasks[-1]


def _user_message(
    text: str,
    *,
    task_id: str | None = None,
    context_id: str | None = None,
    data: dict | None = None,
) -> Message:
    parts: list[Part] = []
    if data is not None:
        parts.append(Part(root=DataPart(data=data)))
    if text:
        parts.append(Part(root=TextPart(text=text)))
    return Message(
        role=Role.user,
        parts=parts,
        message_id=str(uuid4()),
        task_id=task_id,
        context_id=context_id,
    )


def _artifact_text(task: Task) -> str:
    assert task.artifacts, "expected an artifact"
    for artifact in task.artifacts:
        for part in artifact.parts:
            if isinstance(part.root, TextPart):
                return part.root.text
    raise AssertionError("no text artifact")


async def test_send_path_completes(publish_app):
    published = await publish_app(simple_flow(slug="send-flow"))
    flow_id = "send-flow"
    async with published.httpx_client() as hx:
        client = published.a2a_client(flow_id, hx, streaming=False)
        events = [item async for item in client.send_message(_user_message("hi"))]
    task = _final_task(events)
    assert task.status.state == TaskState.completed
    assert _artifact_text(task) == "hello from fake"


async def test_agent_card_served(publish_app):
    published = await publish_app(simple_flow(slug="card-flow"))
    async with published.httpx_client() as hx:
        response = await hx.get("/serve/a2a/card-flow/.well-known/agent-card.json")
    assert response.status_code == 200
    card = response.json()
    assert card["capabilities"]["streaming"] is True
    assert card["url"].endswith("/serve/a2a/card-flow/")


async def test_stream_path_forwards_custom_events(publish_app):
    published = await publish_app(simple_flow(slug="stream-flow"))
    flow_id = "stream-flow"

    bus_events = []

    async def collect_bus():
        async with published.bus.subscribe_flow(flow_id) as queue:
            while True:
                bus_events.append(await queue.get())

    collector = asyncio.create_task(collect_bus())
    try:
        async with published.httpx_client() as hx:
            client = published.a2a_client(flow_id, hx, streaming=True)
            events = [item async for item in client.send_message(_user_message("hi"))]
    finally:
        await asyncio.sleep(0.05)
        collector.cancel()

    task = _final_task(events)
    assert task.status.state == TaskState.completed

    # custom emit() -> working status update carrying a DataPart envelope
    def data_parts():
        for item in events:
            if isinstance(item, tuple) and item[1] is not None:
                update = item[1]
                message = (
                    getattr(update.status, "message", None) if hasattr(update, "status") else None
                )
                if message:
                    for part in message.parts:
                        if isinstance(part.root, DataPart):
                            yield part.root.data

    assert any(d.get("type") == "fake.thinking" for d in data_parts())

    # debug bus mirror got node lifecycle + custom events
    types = {e.type for e in bus_events}
    assert "custom.fake.thinking" in types
    assert "node.start" in types
    assert "status" in types


async def test_interrupt_resume_approved(publish_app):
    published = await publish_app(hitl_flow(slug="hitl-flow"))
    flow_id = "hitl-flow"
    async with published.httpx_client() as hx:
        client = published.a2a_client(flow_id, hx, streaming=False)

        events = [item async for item in client.send_message(_user_message("write something"))]
        task = _final_task(events)
        assert task.status.state == TaskState.input_required
        # interrupt payload surfaced as DataPart on the status message
        payload = next(
            part.root.data for part in task.status.message.parts if isinstance(part.root, DataPart)
        )
        assert payload["kind"] == "approval"
        assert payload["prompt"] == "Release?"

        resume = _user_message(
            "", task_id=task.id, context_id=task.context_id, data={"approved": True}
        )
        events = [item async for item in client.send_message(resume)]
        task = _final_task(events)
        assert task.status.state == TaskState.completed
        assert _artifact_text(task) == "draft answer"


async def test_interrupt_reject_then_approve_cycles(publish_app):
    published = await publish_app(hitl_flow(slug="hitl-cycle"))
    flow_id = "hitl-cycle"
    async with published.httpx_client() as hx:
        client = published.a2a_client(flow_id, hx, streaming=False)

        events = [item async for item in client.send_message(_user_message("draft it"))]
        task = _final_task(events)
        assert task.status.state == TaskState.input_required

        # reject -> cycle back to fake_llm -> interrupts again
        resume = _user_message(
            "",
            task_id=task.id,
            context_id=task.context_id,
            data={"approved": False, "comment": "tighter please"},
        )
        events = [item async for item in client.send_message(resume)]
        task = _final_task(events)
        assert task.status.state == TaskState.input_required

        resume = _user_message(
            "", task_id=task.id, context_id=task.context_id, data={"approved": True}
        )
        events = [item async for item in client.send_message(resume)]
        task = _final_task(events)
        assert task.status.state == TaskState.completed


async def test_multi_turn_same_context(publish_app):
    published = await publish_app(simple_flow(slug="multi-turn", replies=["one", "two"]))
    flow_id = "multi-turn"
    async with published.httpx_client() as hx:
        client = published.a2a_client(flow_id, hx, streaming=False)
        events = [item async for item in client.send_message(_user_message("first"))]
        task1 = _final_task(events)
        assert _artifact_text(task1) == "one"

        follow_up = _user_message("second", context_id=task1.context_id)
        events = [item async for item in client.send_message(follow_up)]
        task2 = _final_task(events)
        assert task2.context_id == task1.context_id
        assert task2.id != task1.id
        assert _artifact_text(task2) == "two"  # thread history persisted


async def test_cancel_running_task(publish_app):
    spec = simple_flow(slug="cancel-flow").model_copy(
        update={
            "nodes": [
                NodeSpec(id="slow", component="slow_node", config={"seconds": 30}),
            ],
            "edges": [
                EdgeSpec(kind="control", source="__start__", target="slow"),
                EdgeSpec(kind="control", source="slow", target="__end__"),
            ],
        }
    )
    published = await publish_app(spec)
    flow_id = "cancel-flow"

    started = asyncio.Event()

    async def watch_bus():
        async with published.bus.subscribe_flow(flow_id) as queue:
            while True:
                event = await queue.get()
                if event.type == "custom.slow.start":
                    started.set()

    watcher = asyncio.create_task(watch_bus())
    async with published.httpx_client() as hx:
        client = published.a2a_client(flow_id, hx, streaming=True)

        async def run():
            return [item async for item in client.send_message(_user_message("go"))]

        runner = asyncio.create_task(run())
        try:
            await asyncio.wait_for(started.wait(), timeout=10)
            # find the running task id via the run registry
            task_ids = list(published.manager.runs._tasks)
            assert task_ids, "run was not registered"
            canceled = await client.cancel_task(TaskIdParams(id=task_ids[0]))
            assert canceled.status.state == TaskState.canceled
        finally:
            watcher.cancel()
            if not runner.done():
                runner.cancel()
