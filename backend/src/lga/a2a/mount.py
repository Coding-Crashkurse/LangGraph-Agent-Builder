"""A2A mounting: per-agent ASGI apps under /a2a/{slug} with auth (SPEC §7.1, §7.11).

Rebuilt on publish/unpublish; the dispatcher swaps sub-apps without restarting.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import httpx
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from starlette.responses import JSONResponse
from starlette.routing import Route

from lga.a2a.card import LEGACY_WELL_KNOWN_PATH, WELL_KNOWN_PATH, build_card
from lga.a2a.executor import LGAAgentExecutor
from lga.a2a.push import DbPushConfigStore, GuardedPushSender
from lga.a2a.scope import current_client_scope, scope_for_api_key, scope_for_ip
from lga.a2a.tasks import DbTaskStore

if TYPE_CHECKING:
    from lga.app import AppServices

logger = logging.getLogger("lga.a2a.mount")

CARD_PATHS = {WELL_KNOWN_PATH, LEGACY_WELL_KNOWN_PATH}


def effective_path(scope: dict) -> str:
    """Path relative to the mount point (Starlette ≥0.35 keeps the full path
    in scope['path'] for ASGI mounts and only advances root_path)."""
    path: str = scope.get("path", "/")
    root: str = scope.get("root_path", "")
    if root and path.startswith(root):
        path = path[len(root):]
    return path or "/"


class _AgentAuthMiddleware:
    """HTTP-layer auth (SPEC §7.10/§7.11): 401 before JSON-RPC ever sees the request."""

    def __init__(self, app: Any, svc: "AppServices", auth_mode: str) -> None:
        self._app = app
        self._svc = svc
        self._auth_mode = auth_mode

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        path = effective_path(scope)
        if path in CARD_PATHS or (scope.get("method") == "GET" and path in ("", "/")):
            await self._app(scope, receive, send)  # cards are public discovery surface
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        api_key = headers.get("x-api-key", "")
        if self._auth_mode == "api-key":
            if not api_key or not await self._svc.apikeys.verify(api_key, "a2a:invoke"):
                response = JSONResponse(
                    {"error": "invalid or missing API key"},
                    status_code=401,
                    headers={"WWW-Authenticate": 'ApiKey header="X-API-Key"'},
                )
                await response(scope, receive, send)
                return
            client_scope = scope_for_api_key(api_key)
        else:
            client = scope.get("client")
            client_scope = scope_for_ip(client[0] if client else "unknown")
        token = current_client_scope.set(client_scope)
        try:
            await self._app(scope, receive, send)
        finally:
            current_client_scope.reset(token)


class A2AManager:
    def __init__(self, svc: "AppServices") -> None:
        self._svc = svc
        self._apps: dict[str, Any] = {}
        self._cards: dict[str, dict[str, Any]] = {}
        self._http = httpx.AsyncClient()

    @property
    def slugs(self) -> list[str]:
        return sorted(self._apps.keys())

    def card_json(self, slug: str) -> dict[str, Any] | None:
        return self._cards.get(slug)

    async def rebuild(self) -> None:
        svc = self._svc
        apps: dict[str, Any] = {}
        cards: dict[str, dict[str, Any]] = {}
        for _flow, version, spec in await svc.flows.published_flows():
            if not spec.flow.a2a.enabled:
                continue
            slug = spec.flow.slug
            try:
                card = build_card(spec, version.semver, svc.settings)
                spec_dict = version.flowspec

                async def spec_provider(_spec: dict = spec_dict) -> dict:
                    return _spec

                agent_executor = LGAAgentExecutor(
                    spec_provider=spec_provider,
                    flow_slug=slug,
                    orchestrator=svc.orchestrator,
                    executor=svc.executor,
                    settings=svc.settings,
                    files_service=svc.files,
                    public=spec.flow.a2a.auth == "public",
                    stream_tokens=spec.flow.a2a.stream_tokens,
                )
                push_store = DbPushConfigStore(svc.sessions, svc.settings)
                handler = DefaultRequestHandler(
                    agent_executor=agent_executor,
                    task_store=DbTaskStore(svc.sessions, slug),
                    push_config_store=push_store,
                    push_sender=GuardedPushSender(self._http, push_store, svc.settings),
                )
                app = A2AStarletteApplication(agent_card=card, http_handler=handler).build(
                    agent_card_url=WELL_KNOWN_PATH, rpc_url="/"
                )
                card_json = json.loads(card.model_dump_json(exclude_none=True, by_alias=True))

                async def card_endpoint(_request: Any, _card: dict = card_json) -> JSONResponse:
                    return JSONResponse(_card)

                # the sdk app already serves both well-known paths; add GET / → card
                app.router.routes.append(Route("/", card_endpoint, methods=["GET"]))
                apps[slug] = _AgentAuthMiddleware(app, svc, spec.flow.a2a.auth)
                cards[slug] = card_json
            except Exception:
                logger.exception("failed to mount A2A agent %s", slug)
        self._apps = apps
        self._cards = cards
        logger.info("A2A agents mounted: %s", ", ".join(sorted(apps)) or "(none)")

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------ dispatcher
    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            return
        path = effective_path(scope)
        segments = [s for s in path.split("/") if s]
        if not segments:
            response = JSONResponse(
                {"detail": "no agent selected", "agents": self.slugs}, status_code=404
            )
            await response(scope, receive, send)
            return
        slug = segments[0]
        app = self._apps.get(slug)
        if app is None:
            response = JSONResponse({"detail": f"unknown agent {slug!r}"}, status_code=404)
            await response(scope, receive, send)
            return
        if (
            self._svc.settings.env == "prod"
            and not self._svc.settings.a2a_allow_http
            and scope.get("scheme") == "http"
        ):
            response = JSONResponse(
                {"detail": "A2A requires https in prod (LGA_A2A_ALLOW_HTTP=true for proxies)"},
                status_code=403,
            )
            await response(scope, receive, send)
            return
        child_scope = dict(scope)
        # advance root_path past the slug; the sub-Starlette-app strips it itself
        child_scope["root_path"] = scope.get("root_path", "") + f"/{slug}"
        await app(child_scope, receive, send)
