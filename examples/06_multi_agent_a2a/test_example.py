import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import LiveServer, load_flow, send_message, text_message, validate_ok  # noqa: E402

HERE = Path(__file__).parent
CHILD = HERE.parent / "04_hitl_approval_a2a"


def test_validates_clean():
    validate_ok(load_flow(HERE))


def test_nested_interrupt_propagation():
    """End-to-end: caller ⇄ orchestrator ⇄ remote agent, nested HITL (SPEC §7.12)."""

    async def _run():
        import httpx

        async with LiveServer() as server:
            await server.publish(load_flow(CHILD))
            orchestrator = load_flow(HERE)
            orchestrator["nodes"][1]["config"]["agent_url"] = f"{server.base}/a2a/hitl-approval"
            await server.publish(orchestrator)

            a2a = f"{server.base}/a2a/orchestrator"
            async with httpx.AsyncClient(timeout=120) as client:
                task = await send_message(client, a2a, text_message("handle the refund"))
                assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", json.dumps(task)[:400]
                data = next(p["data"] for p in task["status"]["message"]["parts"] if "data" in p)
                # the propagated payload mirrors the REMOTE approval prompt
                assert data["prompt"] == "Release this answer?"
                assert data["remote"]["task_id"]

                answer = text_message("", taskId=task["id"], contextId=task["contextId"])
                answer["parts"] = [{"data": {"decision": "approve"}}]
                done = await send_message(client, a2a, answer)
                assert done["status"]["state"] == "TASK_STATE_COMPLETED", json.dumps(done)[:400]
                text = done["artifacts"][0]["parts"][0]["text"]
                assert text.startswith("Draft:")

    asyncio.run(_run())
