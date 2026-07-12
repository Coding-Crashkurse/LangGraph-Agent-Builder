"""FastAPI app factory — design-time API + static frontend, nothing else.

The builder hosts no A2A endpoints, no MCP servers, no execution. Everything
protocol-shaped happens on the agentplane runtime; this app only serves the
builder API (SPEC §3) and the SPA.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import langgraph_agent_builder
from langgraph_agent_builder.auth import AuthenticationError, Authenticator
from langgraph_agent_builder.errors import (
    ConflictError,
    InvalidDefinitionError,
    NotFoundError,
    RuntimeRejectedError,
    RuntimeUnavailableError,
)
from langgraph_agent_builder.services.db import create_engine, create_sessionmaker, create_tables
from langgraph_agent_builder.services.flows import FlowStore
from langgraph_agent_builder.services.runtime import RuntimeGateway
from langgraph_agent_builder.services.settings import Settings, get_settings


@dataclass
class BuilderServices:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    store: FlowStore
    gateway: RuntimeGateway
    authenticator: Authenticator


async def build_services(settings: Settings) -> BuilderServices:
    settings.ensure_dirs()
    engine = create_engine(settings)
    await create_tables(engine)
    sessions = create_sessionmaker(engine)
    return BuilderServices(
        settings=settings,
        engine=engine,
        sessions=sessions,
        store=FlowStore(sessions),
        gateway=RuntimeGateway(settings),
        authenticator=Authenticator(settings),
    )


def _static_dir(settings: Settings) -> Path | None:
    if settings.frontend_path:
        path = Path(settings.frontend_path)
        return path if (path / "index.html").exists() else None
    bundled = Path(__file__).parent / "_static"
    return bundled if (bundled / "index.html").exists() else None


def _cors_origins(settings: Settings) -> list[str]:
    origins = [settings.host_url]
    if settings.env == "dev":
        origins += ["http://localhost:5173", "http://127.0.0.1:5173"]
    return list(dict.fromkeys(origins))


def _issues_payload(issues: list[object], source: str) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for issue in issues:
        dump = issue.model_dump(mode="json") if hasattr(issue, "model_dump") else {}
        dump["source"] = source
        out.append(dump)
    return out


def _register_exception_handlers(app: FastAPI) -> None:
    """Domain-exception → HTTP mapping so routes stay parse-call-serialize."""

    def _detail(status: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
        async def handle(_request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"detail": str(exc)}, status_code=status)

        return handle

    async def invalid_definition(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, InvalidDefinitionError)
        return JSONResponse(
            {"detail": str(exc), "issues": _issues_payload(list(exc.issues), "local")},
            status_code=422,
        )

    async def runtime_rejected(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RuntimeRejectedError)
        return JSONResponse(
            {"detail": str(exc), "issues": _issues_payload(list(exc.issues), "runtime")},
            status_code=422,
        )

    async def unauthorized(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc)},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    app.add_exception_handler(NotFoundError, _detail(404))
    app.add_exception_handler(ConflictError, _detail(409))
    app.add_exception_handler(RuntimeUnavailableError, _detail(503))
    app.add_exception_handler(InvalidDefinitionError, invalid_definition)
    app.add_exception_handler(RuntimeRejectedError, runtime_rejected)
    app.add_exception_handler(AuthenticationError, unauthorized)


def create_app(settings: Settings | None = None, *, backend_only: bool = False) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        svc = await build_services(settings)
        app.state.svc = svc
        try:
            yield
        finally:
            await svc.engine.dispose()

    app = FastAPI(
        title="LangGraph Agent Builder",
        version=langgraph_agent_builder.__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _register_exception_handlers(app)

    from langgraph_agent_builder.api import catalog, config, flows, resources

    app.include_router(flows.router, prefix="/api/v1")
    app.include_router(catalog.router, prefix="/api/v1")
    app.include_router(resources.router, prefix="/api/v1")
    app.include_router(config.router, prefix="/api/v1")

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


# `uvicorn langgraph_agent_builder.app:app_factory --factory` convenience
def app_factory() -> FastAPI:
    return create_app()
