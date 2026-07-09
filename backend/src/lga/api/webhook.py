"""Webhook trigger (SPEC §9.5): raw JSON → data.webhook_payload, fire-and-forget."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request

from lga.api.deps import Services
from lga.services.orchestrator import FlowNotRunnableError

router = APIRouter(tags=["webhook"])


@router.post("/webhook/{id_or_slug}", status_code=202)
async def webhook(
    id_or_slug: str,
    request: Request,
    svc: Services,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> dict[str, Any]:
    if svc.settings.webhook_auth:
        if not (x_api_key and await svc.apikeys.verify(x_api_key, "webhook:invoke")):
            raise HTTPException(401, "webhook auth required (X-API-Key, scope webhook:invoke)")
    flow = await svc.flows.resolve(id_or_slug)
    if flow is None:
        raise HTTPException(404, "flow not found")
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": (await request.body()).decode(errors="replace")}
    header_vars = {
        k.lower().removeprefix("x-lga-var-"): v
        for k, v in request.headers.items()
        if k.lower().startswith("x-lga-var-")
    }
    try:
        # SPEC §10.5: public run endpoints execute the stored definition only —
        # the body lands in data.webhook_payload, tweaks are NOT accepted here.
        run_id, _thread_id, _handle = await svc.orchestrator.start_run(
            spec=flow.spec,
            flow_row=flow,
            mode="api",
            data={"webhook_payload": payload},
            background=True,
            extra_vars=header_vars,
        )
    except FlowNotRunnableError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"run_id": run_id}
