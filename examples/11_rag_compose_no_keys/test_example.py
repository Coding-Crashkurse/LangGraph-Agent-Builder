"""Example 11: real pgvector via compose, fake embeddings, echo model — no keys.

The end-to-end test needs Postgres on :55432 (docker compose up -d postgres)
and skips cleanly when it is down; validation always runs.
"""

import asyncio
import json
import socket
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import load_flow, run_local, validate_ok  # noqa: E402

HERE = Path(__file__).parent

REPO_PG_URL = "postgresql+asyncpg://graphforge:graphforge@localhost:55432/graphforge"


def _postgres_up() -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("localhost", 55432)) == 0


def load_seed_flow() -> dict:
    return json.loads((HERE / "seed_flow.json").read_text(encoding="utf-8"))


def test_flows_validate_clean():
    validate_ok(load_flow(HERE))
    validate_ok(load_seed_flow())


def test_echo_provider_needs_no_keys():
    """The echo model works standalone — flows are testable without secrets."""
    from langgraph_agent_builder.components.llm._models import resolve_model

    async def _run() -> str:
        model = resolve_model({"provider": "echo"})
        result = await model.ainvoke("hello echo")
        return result.content

    assert asyncio.run(_run()) == "hello echo"


@pytest.mark.skipif(not _postgres_up(), reason="postgres :55432 down (docker compose up)")
def test_seed_then_retrieve_end_to_end():
    from langgraph_agent_builder.services.settings import Settings

    collection = f"mini-library-{uuid.uuid4().hex[:8]}"
    settings = Settings(env="test", database_url=REPO_PG_URL)

    seed = load_seed_flow()
    for node in seed["nodes"]:
        if node["id"] == "writer":
            node["config"]["collection"] = collection
    flow = load_flow(HERE)
    for node in flow["nodes"]:
        if node["id"] == "retriever":
            node["config"]["collection"] = collection
            # fake embeddings are deterministic but non-semantic: fetch ALL
            # three docs so the assertion doesn't depend on hash-ranking
            node["config"]["k"] = 3

    def _compile(spec):
        from langgraph_agent_builder.compiler import compile_flow

        return compile_flow(spec, use_cache=False, settings=settings)

    seeded = run_local_compiled(_compile(seed), "go")
    assert seeded.status == "completed", seeded.error_message
    assert '"written": 3' in seeded.result_text

    answer = run_local_compiled(_compile(flow), "Who wrote The Left Hand of Darkness?")
    assert answer.status == "completed", answer.error_message
    # the echo model returns the rendered prompt → retrieved context is visible
    assert "Ursula K. Le Guin" in answer.result_text
    assert "Question: Who wrote The Left Hand of Darkness?" in answer.result_text


def run_local_compiled(compiled, input_text: str):
    from langgraph_agent_builder.runtime.executor import Executor

    async def _run():
        from langgraph.checkpoint.memory import InMemorySaver

        saver = InMemorySaver()

        async def get():
            return saver

        executor = Executor(checkpointer_getter=get)
        return await executor.execute(compiled, input_text=input_text, mode="api")

    return asyncio.run(_run())


def test_run_local_echo_flow_without_db():
    """Sanity: the echo path itself (no retriever) runs on the SQLite-free path."""
    spec = load_flow(HERE)
    # strip the retriever for a db-less smoke: question → echo → end
    spec["nodes"] = [n for n in spec["nodes"] if n["id"] != "retriever"]
    spec["edges"] = [
        e for e in spec["edges"] if e["source"]["node"] != "retriever"
        and e["target"]["node"] != "retriever"
    ]
    result = run_local(spec, input_text="ping?")
    assert result.status == "completed"
    assert "Question: ping?" in result.result_text
