"""Example 12: orchestrator delegating to specialist agents over real A2A HTTP."""

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import LiveServer, send_message, text_message, validate_ok  # noqa: E402

HERE = Path(__file__).parent


def _load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def test_flows_validate_clean():
    validate_ok(_load("greeter_agent.json"))
    validate_ok(_load("shouter_agent.json"))
    validate_ok(_load("orchestrator.json"))


def test_orchestrator_delegates_over_a2a():
    async def _run() -> None:
        async with LiveServer() as server:
            await server.publish(_load("greeter_agent.json"))
            await server.publish(_load("shouter_agent.json"))

            orchestrator = _load("orchestrator.json")
            for node in orchestrator["nodes"]:
                if node["component_id"] == "lab.tools.a2a_remote_agent":
                    slug = node["config"]["agent_url"].rstrip("/").split("/")[-1]
                    node["config"]["agent_url"] = f"{server.base}/a2a/{slug}"
            await server.publish(orchestrator)

            async with httpx.AsyncClient(base_url=server.base, timeout=60) as client:

                async def send(text: str) -> str:
                    task = await send_message(client, "/a2a/orchestrator", text_message(text))
                    assert task["status"]["state"] == "TASK_STATE_COMPLETED", task["status"]
                    return task["artifacts"][0]["parts"][0]["text"]

                shouted = await send("shout: ship it")
                assert shouted == "SHOUT: SHIP IT"

                greeted = await send("please greet our guest")
                assert "greeter agent salutes you" in greeted

    asyncio.run(_run())
