"""GET /node-types — catalog generated from agentplane-core models (SPEC §3)."""

from __future__ import annotations

from agentplane_core import NODE_CATALOG
from httpx import AsyncClient


async def test_catalog_matches_platform_node_set(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/node-types")
    assert resp.status_code == 200
    body = resp.json()
    served = {(t["type"], t["version"]) for t in body["node_types"]}
    assert served == set(NODE_CATALOG)  # exactly the platform catalog, nothing local


async def test_config_schemas_come_from_core_models(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/node-types")).json()
    by_type = {t["type"]: t for t in body["node_types"]}

    llm = by_type["llm_call"]
    assert set(llm["config_schema"]["properties"]) == {
        "resource",
        "model",
        "prompt",
        "system_prompt",
        "structured_output",
        "stream",
        "history",
        "history_max_turns",
    }
    assert llm["dynamic_inputs"] == "prompt_vars"
    assert llm["ui"]["resource"]["widget"] == "resource"
    assert llm["ui"]["resource"]["resource_kind"] == "model_provider"

    retrieval = by_type["retrieval"]
    assert retrieval["inputs"] == [{"name": "query", "type": "text", "label": "Query"}]
    assert retrieval["outputs"][0]["type"] == "documents"

    rerank = by_type["rerank"]
    assert set(rerank["config_schema"]["properties"]) == {"resource", "model", "top_n", "min_score"}
    assert {p["name"] for p in rerank["inputs"]} == {"query", "documents"}
    assert rerank["outputs"][0]["type"] == "documents"
    assert rerank["ui"]["resource"]["resource_kind"] == "model_provider"


async def test_port_rules_exported_for_client_guards(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/node-types")).json()
    assert body["prompt_var_pattern"]
    assert ["documents", "text"] in body["extra_compatible_ports"]
