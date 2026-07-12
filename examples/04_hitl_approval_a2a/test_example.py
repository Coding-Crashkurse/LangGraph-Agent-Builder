import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import LiveServer, load_flow, send_message, text_message, validate_ok  # noqa: E402

HERE = Path(__file__).parent


def test_validates_clean():
    validate_ok(load_flow(HERE))


def test_full_a2a_round_trip():
    async def _run():
        import httpx

        async with LiveServer() as server:
            await server.publish(load_flow(HERE))
            a2a = f"{server.base}/a2a/hitl-approval"
            async with httpx.AsyncClient(timeout=60) as client:
                task = await send_message(client, a2a, text_message("draft it"))
                assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
                data = next(p["data"] for p in task["status"]["message"]["parts"] if "data" in p)
                assert data["kind"] == "approval"

                answer = text_message("", taskId=task["id"], contextId=task["contextId"])
                answer["parts"] = [{"data": {"decision": "approve"}}]
                done = await send_message(client, a2a, answer)
                assert done["status"]["state"] == "TASK_STATE_COMPLETED"
                text = done["artifacts"][0]["parts"][0]["text"]
                assert text.startswith("Draft:")

    asyncio.run(_run())
