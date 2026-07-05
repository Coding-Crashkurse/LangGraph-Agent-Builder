"""FastAPI app factory + lifespan (CLAUDE.md §11 startup order):
engine -> alembic -> AsyncPostgresSaver.setup() -> task store init ->
registry load -> remount published flows."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from a2a.server.tasks import DatabaseTaskStore
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

import graphforge
from graphforge.api import collections as collections_api
from graphforge.api import components as components_api
from graphforge.api import debug as debug_api
from graphforge.api import flows as flows_api
from graphforge.api.flows import spec_from_row
from graphforge.components.registry import registry
from graphforge.db.engine import create_engine, create_sessionmaker
from graphforge.db.models import Flow
from graphforge.runtime.events import EventBus
from graphforge.runtime.manager import FlowRuntimeManager
from graphforge.runtime.runs import RunLog
from graphforge.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def run_alembic_upgrade(settings: Settings) -> None:
    """Upgrade OUR tables (flows, task_events, runs). Library-owned tables
    (a2a task store, checkpoints, pgvector) are set up by their libraries."""
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(graphforge.__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


def _guard_event_loop() -> None:
    """psycopg's async support needs a selector loop on Windows. `graphforge
    serve` and `uvicorn --reload` arrange that; bare `uvicorn` does not."""
    if sys.platform != "win32":
        return
    loop = asyncio.get_running_loop()
    if type(loop).__name__ == "ProactorEventLoop":
        raise RuntimeError(
            "GraphForge needs a selector event loop on Windows (psycopg async). "
            "Start the backend with `uv run graphforge serve` instead of bare uvicorn."
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _guard_event_loop()
        engine = create_engine(app_settings)
        sessionmaker = create_sessionmaker(engine)
        await asyncio.to_thread(run_alembic_upgrade, app_settings)

        pool = AsyncConnectionPool(
            app_settings.psycopg_dsn,
            open=False,
            # validate connections on checkout — idle TCP drops (docker desktop)
            # and postgres restarts must not surface as dead runs
            check=AsyncConnectionPool.check_connection,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()

        task_store = DatabaseTaskStore(engine)
        await task_store.initialize()

        registry.load(include_testing=app_settings.testing)

        bus = EventBus()
        await bus.start(sessionmaker)
        run_log = RunLog(sessionmaker)
        manager = FlowRuntimeManager(
            app,
            settings=app_settings,
            registry=registry,
            bus=bus,
            task_store=task_store,
            checkpointer=checkpointer,
            run_log=run_log,
        )

        app.state.settings = app_settings
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker
        app.state.registry = registry
        app.state.bus = bus
        app.state.manager = manager
        app.state.task_store = task_store
        app.state.checkpointer = checkpointer

        # remount everything that was published before the restart
        async with sessionmaker() as session:
            rows = (
                (await session.execute(select(Flow).where(Flow.is_published.is_(True))))
                .scalars()
                .all()
            )
        for row in rows:
            try:
                await manager.publish_flow(spec_from_row(row))
            except Exception:
                logger.exception("failed to remount published flow '%s'", row.slug)

        logger.info("GraphForge up — %d published flow(s) mounted", len(rows))
        yield

        await manager.shutdown()
        await bus.stop()
        await pool.close()
        await engine.dispose()

    app = FastAPI(title="GraphForge", version=graphforge.__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(components_api.router)
    app.include_router(flows_api.router)
    app.include_router(debug_api.router)
    app.include_router(collections_api.router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": graphforge.__version__}

    @app.exception_handler(DBAPIError)
    async def _db_unreachable(request: Request, exc: DBAPIError) -> JSONResponse:
        # an unreachable database must read as an ops problem, not a bare 500
        logger.error("database error on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "database unreachable — is the postgres container running? "
                "(docker compose up -d postgres)"
            },
        )

    return app


app = create_app()
