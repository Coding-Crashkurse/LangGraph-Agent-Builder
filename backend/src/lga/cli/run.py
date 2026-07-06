"""`lga run` — start the full server (SPEC §2.6)."""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel

from lga.cli._common import build_settings, console, ensure_selector_policy


def _free_port(host: str, port: int, fallback: bool) -> int:
    for candidate in range(port, port + 20 if fallback else port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, candidate))
                return candidate
            except OSError:
                continue
    raise typer.BadParameter(f"port {port} is busy (and fallback disabled/exhausted)")


async def _served_summary(settings) -> tuple[list[str], list[str]]:
    from lga.services.db import create_engine, create_sessionmaker
    from lga.services.flows import FlowService

    engine = create_engine(settings)
    try:
        flows = FlowService(create_sessionmaker(engine))
        a2a, mcp = [], []
        for _flow, _version, spec in await flows.published_flows():
            if spec.flow.a2a.enabled:
                a2a.append(spec.flow.slug)
            if spec.flow.mcp.enabled:
                mcp.append(spec.flow.mcp.tool_name or spec.flow.slug)
        return a2a, mcp
    finally:
        await engine.dispose()


def run_command(
    host: Annotated[str | None, typer.Option(help="Bind host [env: LGA_HOST]")] = None,
    port: Annotated[int | None, typer.Option(help="Bind port [env: LGA_PORT]")] = None,
    env_file: Annotated[Path | None, typer.Option(help="Extra .env file")] = None,
    database_url: Annotated[
        str | None, typer.Option(help="Database URL [env: LGA_DATABASE_URL]")
    ] = None,
    backend_only: Annotated[
        bool, typer.Option("--backend-only", help="Do not serve the bundled frontend")
    ] = False,
    components_path: Annotated[
        list[str] | None,
        typer.Option("--components-path", help="Extra component dir (repeatable)"),
    ] = None,
    log_level: Annotated[str | None, typer.Option(help="Log level [env: LGA_LOG_LEVEL]")] = None,
    workers: Annotated[int, typer.Option(help="Workers (Postgres only)")] = 1,
    reload: Annotated[bool, typer.Option("--reload", help="Dev auto-reload")] = False,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the browser (TTY default)")
    ] = True,
    auto_migrate: Annotated[
        bool, typer.Option("--auto-migrate/--no-auto-migrate", help="Alembic upgrade at boot")
    ] = True,
    port_fallback: Annotated[
        bool, typer.Option("--port-fallback/--no-port-fallback", help="Auto-increment busy port")
    ] = True,
) -> None:
    """Start the full lga server (Studio + A2A + MCP + frontend)."""
    import os

    overrides: dict = {}
    if host is not None:
        overrides["host"] = host
    if port is not None:
        overrides["port"] = port
    if database_url is not None:
        overrides["database_url"] = database_url
    if log_level is not None:
        overrides["log_level"] = log_level
    if components_path:
        overrides["components_path"] = os.pathsep.join(components_path)
    settings = build_settings(env_file, **overrides)
    settings.port = _free_port(settings.host, settings.port, port_fallback)
    if not settings.host_url or settings.host_url == f"http://{settings.host}:{port or 8000}":
        settings.host_url = f"http://{settings.host}:{settings.port}"

    if workers > 1 and settings.is_sqlite:
        console.print("[yellow]--workers >1 requires Postgres; forcing 1 on SQLite[/yellow]")
        workers = 1

    ensure_selector_policy()
    if auto_migrate:
        from lga.db.migrate import upgrade

        upgrade(settings)
    a2a_slugs, mcp_tools = asyncio.new_event_loop().run_until_complete(_served_summary(settings))

    url = f"http://{settings.host}:{settings.port}"
    lines = [
        f"[bold]lga[/bold] ready to serve on [link={url}]{url}[/link]",
        f"database: [cyan]{settings.storage_tier}[/cyan] ({settings.database_url})",
        f"auth: {'[green]on[/green]' if settings.auth_enabled else '[yellow]off (dev)[/yellow]'}",
        f"A2A agents: {', '.join(a2a_slugs) or '(none published)'}  →  {url}/a2a/{{slug}}",
        f"MCP tools:  {', '.join(mcp_tools) or '(none published)'}  →  {url}/mcp",
    ]
    console.print(Panel("\n".join(lines), border_style="cyan", title="lga run"))

    if open_browser and sys.stdout.isatty() and not backend_only:
        import webbrowser

        webbrowser.open(url)

    import uvicorn

    # env for worker/reload subprocesses (they re-read Settings)
    os.environ["LGA_HOST"] = settings.host
    os.environ["LGA_PORT"] = str(settings.port)
    os.environ["LGA_DATABASE_URL"] = settings.database_url
    if backend_only:
        os.environ["LGA_BACKEND_ONLY"] = "1"

    if reload or workers > 1:
        # subprocess servers pick their own (selector-capable) loop
        uvicorn.run(
            "lga.cli.run:asgi_factory",
            factory=True,
            host=settings.host,
            port=settings.port,
            reload=reload,
            workers=None if reload else workers,
            log_level=settings.log_level,
        )
        return
    # single-process: run on OUR selector loop — uvicorn's loop factory would
    # force the Proactor loop on Windows, which psycopg async cannot use
    from lga.app import create_app

    app = create_app(settings, backend_only=backend_only)
    app.state.auto_migrate = False  # already migrated above
    config = uvicorn.Config(
        app, host=settings.host, port=settings.port, log_level=settings.log_level
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


def asgi_factory():
    """Factory for reload/multi-worker subprocesses."""
    import os

    from lga.app import create_app

    return create_app(backend_only=os.environ.get("LGA_BACKEND_ONLY") == "1")
