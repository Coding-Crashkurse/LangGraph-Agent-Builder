"""API-door request/response contract (SPEC §9.3): the public run endpoint serves
the pinned published spec, validates `data` against start.input_schema (422 on
mismatch), and logs — never fails — on end.output_schema drift."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from tests.conftest import create_and_publish, hello_spec

if TYPE_CHECKING:
    import httpx
    import pytest

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


def _reply_spec(slug: str, reply: str) -> dict[str, Any]:
    spec = hello_spec(slug)
    spec["nodes"][1]["config"]["replies"] = [reply]
    return spec


def _input_schema_spec(slug: str) -> dict[str, Any]:
    spec = hello_spec(slug)
    spec["nodes"][0]["config"]["input_schema"] = INPUT_SCHEMA
    return spec


def _structured_output_spec(slug: str, output_schema: dict[str, Any]) -> dict[str, Any]:
    """start --message--> set_data --data--> end.json, with end.output_schema set.
    Set Data emits {"greeting": "hello"} so the run has a structured result."""
    spec = hello_spec(slug)
    spec["nodes"][1] = {
        "id": "setter",
        "component_id": "lab.io.set_data",
        "component_version": "1.0.0",
        "config": {"entries": [{"key": "greeting", "template": "hello"}]},
        "position": {"x": 300, "y": 0},
    }
    spec["nodes"][2]["config"]["output_schema"] = output_schema
    spec["edges"] = [
        {
            "id": "e1",
            "kind": "data",
            "source": {"node": "start", "output": "message"},
            "target": {"node": "setter", "input": "input"},
        },
        {
            "id": "e2",
            "kind": "data",
            "source": {"node": "setter", "output": "data"},
            "target": {"node": "end", "input": "json"},
        },
    ]
    return spec


# -------------------------------------- published vs. draft (SPEC §9.3/§7.1)
async def test_api_mode_runs_pinned_published_spec(client: httpx.AsyncClient) -> None:
    flow_id = await create_and_publish(client, _reply_spec("pinned", "v1 reply"))
    patched = await client.patch(
        f"/api/v1/flows/{flow_id}", json={"spec": _reply_spec("pinned", "draft reply")}
    )
    assert patched.status_code == 200, patched.text

    resp = await client.post("/api/v1/flows/pinned/run", json={"input_text": "hi"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert "v1 reply" in body["result_text"]
    assert "draft reply" not in body["result_text"]
    # the run row is pinned to the published version so resume/thread-state
    # never fall back to the draft graph
    run = await client.get(f"/api/v1/runs/{body['run_id']}")
    assert run.status_code == 200
    assert run.json()["flow_version_id"] is not None


async def test_playground_mode_runs_the_draft(client: httpx.AsyncClient) -> None:
    flow_id = await create_and_publish(client, _reply_spec("pgdraft", "v1 reply"))
    patched = await client.patch(
        f"/api/v1/flows/{flow_id}", json={"spec": _reply_spec("pgdraft", "draft reply")}
    )
    assert patched.status_code == 200, patched.text

    resp = await client.post(
        "/api/v1/flows/pgdraft/run", json={"input_text": "hi", "mode": "playground"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert "draft reply" in body["result_text"]
    run = await client.get(f"/api/v1/runs/{body['run_id']}")
    assert run.json()["flow_version_id"] is None  # draft runs are not pinned


async def test_invalid_input_schema_skips_validation_not_500(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    # author-side schema defect ("required" must be an array): publish is gated
    # by E065 nowadays, but an UNPUBLISHED draft still serves api-mode runs via
    # the fallback — that path must skip validation and log, never 500 (§9.3)
    spec = hello_spec("inbroken")
    spec["nodes"][0]["config"]["input_schema"] = {
        "properties": {"x": {"type": "string"}},
        "required": "x",
    }
    created = await client.post("/api/v1/flows", json={"spec": spec})
    assert created.status_code == 201, created.text
    with caplog.at_level(logging.WARNING, logger="langgraph_agent_builder.api.runs"):
        resp = await client.post(
            "/api/v1/flows/inbroken/run", json={"input_text": "hi", "data": {"x": "ok"}}
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"
    assert any("could not be applied" in r.message for r in caplog.records)


# --------------------------------------------- request contract: input_schema
async def test_data_violating_input_schema_is_422(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, _input_schema_spec("inbad"))
    resp = await client.post(
        "/api/v1/flows/inbad/run", json={"input_text": "hi", "data": {"name": 5}}
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "input does not match the flow's input_schema"
    assert "is not of type 'string'" in detail["detail"]


async def test_valid_data_passes_input_schema(client: httpx.AsyncClient) -> None:
    await create_and_publish(client, _input_schema_spec("ingood"))
    resp = await client.post(
        "/api/v1/flows/ingood/run", json={"input_text": "hi", "data": {"name": "Ada"}}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"


async def test_text_only_call_skips_input_schema(client: httpx.AsyncClient) -> None:
    # data=None must stay valid even when the flow declares an input_schema
    await create_and_publish(client, _input_schema_spec("intext"))
    resp = await client.post("/api/v1/flows/intext/run", json={"input_text": "hi"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"


# -------------------------------------------- response contract: output_schema
async def test_output_schema_mismatch_logs_warning_but_completes(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    schema = {
        "type": "object",
        "properties": {"greeting": {"type": "number"}},
        "required": ["greeting"],
    }
    await create_and_publish(client, _structured_output_spec("outbad", schema))
    with caplog.at_level(logging.WARNING, logger="langgraph_agent_builder.api.runs"):
        resp = await client.post("/api/v1/flows/outbad/run", json={"input_text": "hi"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["result_json"] == {"greeting": "hello"}
    assert any("does not match the flow's output_schema" in r.message for r in caplog.records)


async def test_matching_structured_result_logs_nothing(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    schema = {
        "type": "object",
        "properties": {"greeting": {"type": "string"}},
        "required": ["greeting"],
    }
    await create_and_publish(client, _structured_output_spec("outgood", schema))
    with caplog.at_level(logging.WARNING, logger="langgraph_agent_builder.api.runs"):
        resp = await client.post("/api/v1/flows/outgood/run", json={"input_text": "hi"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["result_json"] == {"greeting": "hello"}
    assert not [r for r in caplog.records if "output_schema" in r.message]
