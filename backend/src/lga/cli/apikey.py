"""`lga apikey` — headless key management, direct DB (SPEC §2.6, §10.4)."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.table import Table

from lga.cli._common import build_settings, console, err_console, run_async

apikey_app = typer.Typer(help="Manage API keys (direct DB; works without a running server).")


async def _service():
    from lga.services.apikeys import ApiKeyService
    from lga.services.db import create_engine, create_sessionmaker
    from lga.services.settings import get_settings

    settings = get_settings()
    from lga.db.migrate import upgrade_async

    await upgrade_async(settings)
    engine = create_engine(settings)
    return ApiKeyService(create_sessionmaker(engine)), engine


@apikey_app.command("create")
def create(
    scopes: Annotated[list[str], typer.Option("--scopes", "-s", help="Repeatable scope")],
    name: Annotated[str, typer.Option("--name")] = "",
    json_out: Annotated[bool, typer.Option("--json/--no-json")] = False,
) -> None:
    build_settings(None)

    async def _run():
        service, engine = await _service()
        try:
            return await service.create(scopes, name)
        finally:
            await engine.dispose()

    try:
        key, info = run_async(_run())
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    if json_out:
        print(json.dumps({**info, "key": key}))
    else:
        console.print(f"[green]created[/green] {info['id']} ({', '.join(scopes)})")
        console.print(f"[bold]key (shown once):[/bold] {key}")


@apikey_app.command("list")
def list_keys(json_out: Annotated[bool, typer.Option("--json/--no-json")] = False) -> None:
    build_settings(None)

    async def _run():
        service, engine = await _service()
        try:
            return await service.list()
        finally:
            await engine.dispose()

    keys = run_async(_run())
    if json_out:
        print(json.dumps(keys, indent=2))
        return
    table = Table("id", "name", "prefix", "scopes", "uses", "revoked")
    for k in keys:
        table.add_row(
            k["id"],
            k["name"],
            k["prefix"],
            ",".join(k["scopes"]),
            str(k["total_uses"]),
            "yes" if k["revoked"] else "",
        )
    console.print(table)


@apikey_app.command("revoke")
def revoke(key_id: Annotated[str, typer.Argument()]) -> None:
    build_settings(None)

    async def _run():
        service, engine = await _service()
        try:
            return await service.revoke(key_id)
        finally:
            await engine.dispose()

    if run_async(_run()):
        console.print(f"[green]revoked[/green] {key_id}")
    else:
        err_console.print("[red]key not found[/red]")
        raise typer.Exit(1)
