"""lab CLI (SPEC §2.6). Config precedence: flag > env > --env-file > ./.env > defaults."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from langgraph_agent_builder.cli._common import build_settings, console
from langgraph_agent_builder.cli.apikey import apikey_app
from langgraph_agent_builder.cli.component import component_new
from langgraph_agent_builder.cli.flow import flow_app
from langgraph_agent_builder.cli.init import init_command
from langgraph_agent_builder.cli.run import run_command

app = typer.Typer(
    name="lab",
    help="LangGraph-native visual agent builder — Studio, A2A agents, MCP tools.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.command("run")(run_command)
app.command("start", hidden=True)(run_command)  # alias
app.command("init")(init_command)
app.add_typer(flow_app, name="flow")
app.command("component-new", hidden=True)(component_new)
component_app = typer.Typer(help="Component authoring helpers.")
component_app.command("new")(component_new)
app.add_typer(component_app, name="component")
app.add_typer(apikey_app, name="apikey")


@app.command()
def migrate(
    revision: Annotated[str, typer.Option(help="Target revision")] = "head",
    sql: Annotated[bool, typer.Option("--sql", help="Offline: print SQL only")] = False,
    env_file: Annotated[Path | None, typer.Option(help="Extra .env file")] = None,
) -> None:
    """Alembic upgrade against the resolved database."""
    settings = build_settings(env_file)
    from langgraph_agent_builder.db.migrate import offline_sql, upgrade

    if sql:
        offline_sql(settings, revision)
    else:
        upgrade(settings, revision)
        console.print(f"[green]migrated[/green] {settings.database_url} → {revision}")


@app.command()
def config(
    env_file: Annotated[Path | None, typer.Option(help="Extra .env file")] = None,
    json_out: Annotated[bool, typer.Option("--json/--no-json")] = False,
) -> None:
    """Print the effective resolved config (secrets masked) + source per key."""
    settings = build_settings(env_file)
    data = settings.model_dump(mode="json")
    data["secret_key"] = "***" if settings.secret_key else ""
    rows = []
    for key, value in sorted(data.items()):
        env_key = f"LAB_{key.upper()}"
        source = "env/.env" if env_key in os.environ else "default"
        rows.append({"key": env_key, "value": value, "source": source})
    if json_out:
        print(json.dumps(rows, indent=2, default=str))
        return
    from rich.table import Table

    table = Table("key", "value", "source")
    for row in rows:
        table.add_row(row["key"], str(row["value"]), row["source"])
    console.print(table)


@app.command()
def version(json_out: Annotated[bool, typer.Option("--json/--no-json")] = False) -> None:
    """Package version, A2A protocolVersion, LangGraph version, DB backend."""
    import importlib.metadata

    import langgraph_agent_builder as lab_pkg

    settings = build_settings(None)
    try:
        from a2a.utils.constants import PROTOCOL_VERSION_CURRENT

        protocol = PROTOCOL_VERSION_CURRENT
    except Exception:
        protocol = "1.0"
    try:
        langgraph_version = importlib.metadata.version("langgraph")
    except importlib.metadata.PackageNotFoundError:
        langgraph_version = "unknown"
    from langgraph_agent_builder.vectorstores import installed_backends

    info = {
        "langgraph-agent-builder": lab_pkg.__version__,
        "a2a_protocol": str(protocol),
        "langgraph": langgraph_version,
        "db_backend": settings.storage_tier,
        "vector_backends": installed_backends(),
    }
    if json_out:
        print(json.dumps(info))
    else:
        for key, value in info.items():
            console.print(f"{key}: [bold]{value}[/bold]")


if __name__ == "__main__":
    app()
