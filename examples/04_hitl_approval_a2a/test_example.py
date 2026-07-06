import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import LiveServer, load_flow, rpc, text_message, validate_ok  # noqa: E402

HERE = Path(__file__).parent


def test_validates_clean():
    validate_ok(load_flow(HERE))


def test_full_a2a_round_trip():
    async def _run():
        import httpx

        async with LiveServer() as server:
            await server.publish(load_flow(HERE))
            endpoint = f"{server.base}/a2a/hitl-approval/"
            async with httpx.AsyncClient(timeout=60) as client:
                task = (await client.post(endpoint, json=rpc(
                    "message/send", {"message": text_message("draft it")}
                ))).json()["result"]
                assert task["status"]["state"] == "input-required"
                data = next(p["data"] for p in task["status"]["message"]["parts"]
                            if p["kind"] == "data")
                assert data["kind"] == "approval"

                answer = text_message("", taskId=task["id"], contextId=task["contextId"])
                answer["parts"] = [{"kind": "data", "data": {"decision": "approve"}}]
                done = (await client.post(endpoint, json=rpc(
                    "message/send", {"message": answer}
                ))).json()["result"]
                assert done["status"]["state"] == "completed"
                text = done["artifacts"][0]["parts"][0]["text"]
                assert text.startswith("Draft:")

    asyncio.run(_run())
