"""A2A mounting: per-agent ASGI apps under /a2a/{slug} with auth (SPEC §7.1, §7.11).

Rebuilt on publish/unpublish; the dispatcher swaps sub-apps without restarting.

a2a-sdk 1.x (protocol v1.0) serves a REST HTTP+JSON door: the route factories in
``a2a.server.routes`` (``create_agent_card_routes`` + ``create_rest_routes``)
produce Starlette routes we hang off a per-flow ``Starlette`` sub-app. The 0.3
``A2AStarletteApplication`` + ``JSONRPCHandler`` are gone; push-capability honesty
(§7.9/§7.10) and resubscribe replay (§7.5) are now native to the request handler
(see handler.py), so this module only wires + mounts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.server.routes import (
    DefaultServerCallContextBuilder,
    create_agent_card_routes,
    create_rest_routes,
)
from a2a.utils.constants import PROTOCOL_VERSION_1_0, VERSION_HEADER
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from langgraph_agent_builder.a2a.card import WELL_KNOWN_PATH, build_card
from langgraph_agent_builder.a2a.executor import LabAgentExecutor
from langgraph_agent_builder.a2a.handler import LabRequestHandler
from langgraph_agent_builder.a2a.push import DbPushConfigStore, GuardedPushSender
from langgraph_agent_builder.a2a.scope import current_client_scope, scope_for_api_key, scope_for_ip
from langgraph_agent_builder.a2a.tasks import resolve_task_store

if TYPE_CHECKING:
    from a2a.server.context import ServerCallContext
    from starlette.requests import Request

    from langgraph_agent_builder.app import AppServices

logger = logging.getLogger("langgraph_agent_builder.a2a.mount")

# v1.0 serves the single well-known card path (agent.json is gone).
CARD_PATHS = {WELL_KNOWN_PATH}


class _LabContextBuilder(DefaultServerCallContextBuilder):
    """Default the ``A2A-Version`` header to 1.0 and freeze the per-request client
    scope. The SDK treats a missing version header as 0.3, but our door only
    speaks v1.0 (D4: no v0.3 compat), so an unversioned request is 1.0. An
    explicit header is preserved (a genuine 0.3 client still gets 400). The auth
    middleware's contextvar is snapshotted into call-context state so
    ``resolve_client_scope`` stays correct across ActiveTask background tasks."""

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        headers = context.state.setdefault("headers", {})
        if not (headers.get(VERSION_HEADER) or headers.get(VERSION_HEADER.lower())):
            headers[VERSION_HEADER] = PROTOCOL_VERSION_1_0
        scope = current_client_scope.get()
        if scope:
            context.state["lga_client_scope"] = scope
        return context


def effective_path(scope: dict[str, Any]) -> str:
    """Path relative to the mount point (Starlette ≥0.35 keeps the full path
    in scope['path'] for ASGI mounts and only advances root_path)."""
    path: str = scope.get("path", "/")
    root: str = scope.get("root_path", "")
    if root and path.startswith(root):
        path = path[len(root) :]
    return path or "/"


class _AgentAuthMiddleware:
    """HTTP-layer auth (SPEC §7.10/§7.11): 401 before the REST handler sees the request."""

    def __init__(self, app: Any, svc: AppServices, auth_mode: str) -> None:
        self._app = app
        self._svc = svc
        self._auth_mode = auth_mode

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
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
    def __init__(self, svc: AppServices) -> None:
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

                async def spec_provider(
                    _spec: dict[str, Any] = spec_dict,
                ) -> dict[str, Any]:
                    return _spec

                agent_executor = LabAgentExecutor(
                    spec_provider=spec_provider,
                    flow_slug=slug,
                    orchestrator=svc.orchestrator,
                    executor=svc.executor,
                    settings=svc.settings,
                    files_service=svc.files,
                    public=spec.flow.a2a.auth == "public",
                    stream_tokens=spec.flow.a2a.stream_tokens,
                )
                # push honesty (§7.9): card says pushNotifications:false ⇒ no
                # store/sender wired, and the handler's native capability gate
                # answers PUSH_NOTIFICATION_NOT_SUPPORTED for every push method.
                push_enabled = spec.flow.a2a.push_notifications
                push_store = DbPushConfigStore(svc.sessions, svc.settings) if push_enabled else None
                handler = LabRequestHandler(
                    agent_executor=agent_executor,
                    task_store=resolve_task_store(
                        svc.settings.a2a_task_store,
                        sessions=svc.sessions,
                        flow_slug=slug,
                        settings=svc.settings,
                    ),
                    agent_card=card,
                    push_config_store=push_store,
                    push_sender=(
                        GuardedPushSender(self._http, push_store, svc.settings)
                        if push_store is not None
                        else None
                    ),
                    # v1 extended card == public card (§7.5); flip the card's
                    # capability flag later to diverge without protocol changes
                    extended_agent_card=card,
                )
                card_dict = agent_card_to_dict(card)

                async def card_endpoint(
                    _request: Any, _card: dict[str, Any] = card_dict
                ) -> JSONResponse:
                    return JSONResponse(_card)

                # REST HTTP+JSON door: card route + GET / convenience + the
                # message:send/tasks/* endpoints, all relative to /a2a/{slug}
                routes = [
                    *create_agent_card_routes(card, card_url=WELL_KNOWN_PATH),
                    Route("/", card_endpoint, methods=["GET"]),
                    *create_rest_routes(handler, context_builder=_LabContextBuilder()),
                ]
                sub_app = Starlette(routes=routes)
                apps[slug] = _AgentAuthMiddleware(sub_app, svc, spec.flow.a2a.auth)
                cards[slug] = card_dict
            except Exception:
                logger.exception("failed to mount A2A agent %s", slug)
        self._apps = apps
        self._cards = cards
        logger.info("A2A agents mounted: %s", ", ".join(sorted(apps)) or "(none)")

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------ dispatcher
    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
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
                {"detail": "A2A requires https in prod (LAB_A2A_ALLOW_HTTP=true for proxies)"},
                status_code=403,
            )
            await response(scope, receive, send)
            return
        child_scope = dict(scope)
        # advance root_path past the slug; the sub-Starlette-app strips it itself
        child_scope["root_path"] = scope.get("root_path", "") + f"/{slug}"
        await app(child_scope, receive, send)
