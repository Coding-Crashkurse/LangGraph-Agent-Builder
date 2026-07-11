"""FastAPI app factory (SPEC §2.4): Studio API + A2A + MCP + static frontend."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from langgraph_agent_builder.errors import LabValueError
from langgraph_agent_builder.runtime.checkpoint import CheckpointerFactory
from langgraph_agent_builder.runtime.executor import Executor
from langgraph_agent_builder.runtime.streams import EventBus
from langgraph_agent_builder.sdk.registry import ComponentRegistry, get_registry
from langgraph_agent_builder.services.errors import ConflictError, NotFoundError
from langgraph_agent_builder.services.settings import Settings, get_settings

if TYPE_CHECKING:
    from langgraph_agent_builder.a2a.mount import A2AManager
    from langgraph_agent_builder.mcp.server import McpManager
    from langgraph_agent_builder.services.apikeys import ApiKeyService
    from langgraph_agent_builder.services.files import FilesService
    from langgraph_agent_builder.services.flows import FlowService
    from langgraph_agent_builder.services.mcp_servers import McpServersService
    from langgraph_agent_builder.services.orchestrator import Orchestrator
    from langgraph_agent_builder.services.resources import ResourcesService
    from langgraph_agent_builder.services.runs import RunService
    from langgraph_agent_builder.services.secrets import SecretsService
    from langgraph_agent_builder.services.vectorstores import VectorStoreService

logger = logging.getLogger("langgraph_agent_builder.app")


@dataclass
class AppServices:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    registry: ComponentRegistry
    checkpointers: CheckpointerFactory
    bus: EventBus
    executor: Executor
    flows: FlowService
    runs: RunService
    secrets: SecretsService
    apikeys: ApiKeyService
    files: FilesService
    mcp_servers: McpServersService
    vectorstores: VectorStoreService
    resources: ResourcesService
    orchestrator: Orchestrator
    a2a: A2AManager | None = None
    mcp: McpManager | None = None
    tasks: list[asyncio.Task[None]] = field(default_factory=list)

    async def remount(self) -> None:
        """Re-mount published flows after publish/unpublish/delete."""
        if self.a2a is not None:
            await self.a2a.rebuild()
        if self.mcp is not None:
            await self.mcp.rebuild()


async def build_services(settings: Settings) -> AppServices:
    from langgraph_agent_builder.services.apikeys import ApiKeyService
    from langgraph_agent_builder.services.db import create_engine, create_sessionmaker
    from langgraph_agent_builder.services.files import FilesService
    from langgraph_agent_builder.services.flows import FlowService
    from langgraph_agent_builder.services.mcp_servers import McpServersService
    from langgraph_agent_builder.services.orchestrator import Orchestrator
    from langgraph_agent_builder.services.resources import ResourcesService
    from langgraph_agent_builder.services.runs import RunService
    from langgraph_agent_builder.services.secrets import SecretsService
    from langgraph_agent_builder.services.vectorstores import VectorStoreService

    settings.ensure_dirs()
    engine = create_engine(settings)
    sessions = create_sessionmaker(engine)
    runs = RunService(sessions)
    bus = EventBus(persist=runs.persist_event, load=runs.load_events)
    checkpointers = CheckpointerFactory(settings)
    executor = Executor(
        checkpointer_getter=checkpointers.get,
        bus=bus,
        on_status=runs.update_status,
        recursion_limit_default=settings.recursion_limit_default,
        preview_length=settings.max_text_length,
    )
    registry = get_registry()
    for directory in settings.component_dirs():
        registry.scan_dir(directory)
    secrets = SecretsService(settings, sessions)
    vectorstores = VectorStoreService(settings, sessions, secrets)
    mcp_servers = McpServersService(sessions)
    resources = ResourcesService(settings, sessions, secrets, mcp_servers, vectorstores)
    orchestrator = Orchestrator(
        settings=settings,
        registry=registry,
        secrets=secrets,
        runs=runs,
        executor=executor,
        vectorstores=vectorstores,
        resources=resources,
    )
    services = AppServices(
        settings=settings,
        engine=engine,
        sessions=sessions,
        registry=registry,
        checkpointers=checkpointers,
        bus=bus,
        executor=executor,
        flows=FlowService(sessions),
        runs=runs,
        secrets=secrets,
        apikeys=ApiKeyService(sessions, track_usage=settings.track_apikey_usage),
        files=FilesService(settings, sessions),
        mcp_servers=mcp_servers,
        vectorstores=vectorstores,
        resources=resources,
        orchestrator=orchestrator,
    )
    from langgraph_agent_builder.services.locator import set_services

    set_services(services)
    return services


def _static_dir(settings: Settings) -> Path | None:
    if settings.frontend_path:
        path = Path(settings.frontend_path)
        return path if (path / "index.html").exists() else None
    bundled = Path(__file__).parent / "_static"
    return bundled if (bundled / "index.html").exists() else None


def _cors_origins(settings: Settings) -> list[str]:
    """SPEC §10.5: CORS locked to the frontend origin; Vite dev hosts only in dev."""
    origins = [settings.host_url]
    if settings.env == "dev":
        origins += ["http://localhost:5173", "http://127.0.0.1:5173"]
    return list(dict.fromkeys(origins))


def _register_exception_handlers(app: FastAPI) -> None:
    """Domain-exception → HTTP mapping so routes stay parse-call-serialize."""

    def _detail_handler(status: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
        async def handle(_request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"detail": str(exc)}, status_code=status)

        return handle

    async def integrity(_request: Request, _exc: Exception) -> JSONResponse:
        # unique-constraint race that no service translated — never a 500,
        # and never leak the SQL statement to the client
        return JSONResponse({"detail": "conflicting concurrent write — retry"}, status_code=409)

    app.add_exception_handler(NotFoundError, _detail_handler(404))
    app.add_exception_handler(ConflictError, _detail_handler(409))
    app.add_exception_handler(LabValueError, _detail_handler(422))
    app.add_exception_handler(IntegrityError, integrity)


async def _shutdown(svc: AppServices) -> None:
    for task in svc.tasks:
        task.cancel()
    # aclose, not drain: flushing alone leaves the persist task pending —
    # "Task was destroyed but it is pending!" at interpreter shutdown
    await svc.bus.aclose()
    if svc.a2a is not None:
        await svc.a2a.aclose()
    await svc.checkpointers.aclose()
    await svc.engine.dispose()


def create_app(settings: Settings | None = None, *, backend_only: bool = False) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from langgraph_agent_builder.a2a.mount import A2AManager
        from langgraph_agent_builder.db.migrate import upgrade_async
        from langgraph_agent_builder.mcp.server import McpAuthMiddleware, McpManager
        from langgraph_agent_builder.schema.scrub import install_log_scrubbing
        from langgraph_agent_builder.services import bootstrap

        # runs after uvicorn has configured its handlers → scrubs console + file
        # logs. Event scrubbing (the hard guarantee) lives in the event bus (§10.5)
        install_log_scrubbing()

        if getattr(app.state, "auto_migrate", True):
            await upgrade_async(settings)
        svc = await build_services(settings)
        svc.a2a = A2AManager(svc)
        mcp_manager = McpManager(svc)
        svc.mcp = mcp_manager
        app.state.svc = svc

        # boot provisioning (SPEC §18.1) before mounting: published imports serve
        await bootstrap.provision(svc)

        # dynamic protocol mounts — inserted at the front so the SPA catch-all
        # (registered at create_app time) can never shadow /a2a and /mcp
        for route in reversed(_protocol_routes(svc, McpAuthMiddleware)):
            app.router.routes.insert(0, route)

        bootstrap.start_background_tasks(svc)

        async with mcp_manager.mcp.session_manager.run():
            try:
                yield
            finally:
                await _shutdown(svc)

    app = FastAPI(title="LangGraph Agent Builder", version=_version(), lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _register_exception_handlers(app)

    from langgraph_agent_builder.api import (
        components,
        flows,
        resources,
        runs,
        settings_api,
        templates,
        vectorstores,
        webhook,
    )

    app.include_router(flows.router, prefix="/api/v1")
    app.include_router(components.router, prefix="/api/v1")
    app.include_router(runs.router, prefix="/api/v1")
    app.include_router(vectorstores.router, prefix="/api/v1")
    app.include_router(resources.router, prefix="/api/v1")
    app.include_router(templates.router, prefix="/api/v1")
    app.include_router(settings_api.router, prefix="/api/v1")
    app.include_router(settings_api.misc_router, prefix="/api/v1")
    app.include_router(settings_api.health_router, prefix="/api/v1")
    app.include_router(settings_api.public_files_router, prefix="/api/v1")
    app.include_router(webhook.router, prefix="/api/v1")
    # unprefixed health ONLY for load balancers + packaging tests — /version
    # and /config stay under /api/v1 (they were never meant to be root routes)
    app.include_router(settings_api.health_router, include_in_schema=False)

    @app.get("/.well-known/agent-card.json", include_in_schema=False)
    @app.get("/.well-known/agent.json", include_in_schema=False)
    async def well_known_root() -> JSONResponse:
        svc: AppServices = app.state.svc
        agents = {
            slug: f"{settings.host_url}/a2a/{slug}/.well-known/agent-card.json"
            for slug in (svc.a2a.slugs if svc.a2a else [])
        }
        return JSONResponse(
            {
                "detail": "per-agent cards live under /a2a/{slug}/.well-known/agent-card.json",
                "agents": agents,
            },
            status_code=404 if not agents else 200,
        )

    # static frontend with SPA fallback (SPEC §2.5)
    static = None if backend_only else _static_dir(settings)
    if static is not None:
        from fastapi.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            candidate = static / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static / "index.html")

    return app


def _protocol_routes(svc: AppServices, mcp_auth_cls: Any) -> list[Any]:
    from starlette.routing import Mount

    assert svc.a2a is not None
    assert svc.mcp is not None
    a2a_app: Any = svc.a2a
    mcp_http = mcp_auth_cls(svc.mcp.http_app(), svc)
    mcp_sse = mcp_auth_cls(svc.mcp.sse_app(), svc)
    return [
        Mount("/a2a", app=a2a_app),
        Mount("/mcp/sse", app=mcp_sse),
        Mount("/mcp", app=mcp_http),
    ]


def _version() -> str:
    import langgraph_agent_builder

    return langgraph_agent_builder.__version__


# `uvicorn langgraph_agent_builder.app:app` convenience (dev; the CLI is the blessed entry)
def app_factory() -> FastAPI:
    return create_app()
