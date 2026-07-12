"""The ``lab`` CLI — serve the builder; deploys belong to the platform CLI."""

from __future__ import annotations

import typer

import langgraph_agent_builder

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def serve(
    host: str = typer.Option(None, help="bind host (default: BUILDER_HOST)"),
    port: int = typer.Option(None, help="bind port (default: BUILDER_PORT)"),
    reload: bool = typer.Option(False, help="dev auto-reload"),
) -> None:
    """Run the builder (design-time API + bundled frontend)."""
    import uvicorn

    from langgraph_agent_builder.services.settings import get_settings

    settings = get_settings()
    uvicorn.run(
        "langgraph_agent_builder.app:app_factory",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        log_level=settings.log_level,
    )


@app.command()
def version() -> None:
    """Print the builder version."""
    typer.echo(langgraph_agent_builder.__version__)


if __name__ == "__main__":
    app()
