"""Example 13 — RAG over the zero-config local vector store (SPEC §8b, §13).

Seeds a collection with a splitter+writer flow, then retrieves from it — all on
the `local` backend with deterministic fake embeddings: no API keys, no server.
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import LiveServer, load_flow, validate_ok  # noqa: E402

HERE = Path(__file__).parent

DOCUMENT = (
    "The lga compiler turns a FlowSpec into a real LangGraph StateGraph. "
    "The local vector store uses exact cosine search and needs no server. "
    "Every published flow is a spec-compliant A2A agent."
)


def _seed_flow() -> dict:
    return json.loads((HERE / "seed_flow.json").read_text(encoding="utf-8"))


def test_both_flows_validate_clean():
    validate_ok(load_flow(HERE))
    validate_ok(_seed_flow())


def test_seed_then_retrieve_local():
    async def scenario() -> None:
        async with LiveServer() as server, httpx.AsyncClient(
            base_url=server.base, timeout=30
        ) as client:
            # 1. seed the local `kb` collection
            seed = (await client.post("/api/v1/flows", json={"spec": _seed_flow()})).json()
            seeded = await client.post(
                f"/api/v1/flows/{seed['slug']}/run", json={"input_text": DOCUMENT}
            )
            assert seeded.json()["status"] == "completed", seeded.text

            # 2. retrieve from the same store (slug-first run URL)
            query = (await client.post("/api/v1/flows", json={"spec": load_flow(HERE)})).json()
            retrieved = await client.post(
                f"/api/v1/flows/{query['slug']}/run",
                json={"input_text": "how does the local vector store search?"},
            )
            body = retrieved.json()
            assert body["status"] == "completed", retrieved.text
            assert "cosine" in (body["result_text"] or "")

    asyncio.run(scenario())
