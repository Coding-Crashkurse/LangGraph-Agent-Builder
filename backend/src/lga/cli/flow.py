"""`lga flow` — headless flow ops (SPEC §2.6): import/export/validate/publish/run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import httpx
import typer

from lga.cli._common import (
    EXIT_CONNECTION,
    EXIT_VALIDATION,
    console,
    err_console,
    run_async,
)

flow_app = typer.Typer(help="Headless flow operations (server-based or --local).")

ServerOpt = Annotated[str, typer.Option(envvar="LGA_SERVER_URL", help="lga server URL")]
ApiKeyOpt = Annotated[str | None, typer.Option(envvar="LGA_API_KEY", help="API key (studio scope)")]


def _client(server: str, api_key: str | None) -> httpx.Client:
    headers = {"X-API-Key": api_key} if api_key else {}
    return httpx.Client(base_url=server.rstrip("/"), headers=headers, timeout=60.0)


def _request(client: httpx.Client, method: str, path: str, **kwargs):
    try:
        response = client.request(method, path, **kwargs)
    except httpx.ConnectError as exc:
        err_console.print(f"[red]cannot reach server:[/red] {exc}")
        raise typer.Exit(EXIT_CONNECTION) from exc
    if response.status_code == 401:
        err_console.print("[red]authentication failed[/red] (set --api-key / LGA_API_KEY)")
        raise typer.Exit(EXIT_CONNECTION)
    return response


@flow_app.command("import")
def import_flows(
    paths: Annotated[list[Path], typer.Argument(help="FlowSpec JSON files")],
    server: ServerOpt = "http://127.0.0.1:8000",
    api_key: ApiKeyOpt = None,
) -> None:
    """Import FlowSpec files via POST /flows/import."""
    with _client(server, api_key) as client:
        for path in paths:
            spec = json.loads(path.read_text(encoding="utf-8"))
            response = _request(client, "POST", "/api/v1/flows/import", json={"spec": spec})
            if response.status_code == 409:
                # slug exists → update the draft in place
                slug = spec.get("flow", {}).get("slug", "")
                existing = _request(client, "GET", "/api/v1/flows").json()
                target = next((f for f in existing if f["slug"] == slug), None)
                if target:
                    response = _request(
                        client, "PATCH", f"/api/v1/flows/{target['id']}", json={"spec": spec}
                    )
            response.raise_for_status()
            info = response.json()
            console.print(f"[green]imported[/green] {path.name} → {info['id']} ({info['slug']})")


@flow_app.command("export")
def export_flow(
    flow_id: Annotated[str, typer.Argument(help="Flow id or slug")],
    format: Annotated[str, typer.Option(help="json | python")] = "json",
    server: ServerOpt = "http://127.0.0.1:8000",
    api_key: ApiKeyOpt = None,
) -> None:
    with _client(server, api_key) as client:
        flow_id = _resolve_id(client, flow_id)
        response = _request(
            client, "GET", f"/api/v1/flows/{flow_id}/export", params={"format": format}
        )
        response.raise_for_status()
        print(response.text if format == "python" else json.dumps(response.json(), indent=2))


def _resolve_id(client: httpx.Client, ref: str) -> str:
    flows = _request(client, "GET", "/api/v1/flows").json()
    for flow in flows:
        if flow["id"] == ref or flow["slug"] == ref:
            return flow["id"]
    err_console.print(f"[red]flow {ref!r} not found on server[/red]")
    raise typer.Exit(EXIT_CONNECTION)


@flow_app.command("validate")
def validate_flow(
    path: Annotated[Path, typer.Argument(help="FlowSpec JSON file")],
    deep: Annotated[bool, typer.Option("--deep", help="Run health checks too")] = False,
    format: Annotated[str, typer.Option(help="text | json")] = "text",
) -> None:
    """In-process compile+validate; exits 3 on ERROR diagnostics (CI-friendly)."""
    from lga.compiler import compile_flow
    from lga.schema.diagnostics import Severity

    compiled = compile_flow(json.loads(path.read_text(encoding="utf-8")), use_cache=False)
    diags = compiled.diagnostics
    if format == "json":
        print(json.dumps([d.model_dump(mode="json") for d in diags], indent=2))
    else:
        if not diags:
            console.print(f"[green]{path.name}: no diagnostics[/green]")
        for d in diags:
            color = {"error": "red", "warning": "yellow", "info": "cyan"}[d.severity.value]
            where = f" [{d.node_id or d.edge_id or ''}]" if (d.node_id or d.edge_id) else ""
            console.print(f"[{color}]{d.code.value}[/{color}]{where} {d.message}")
    if any(d.severity == Severity.ERROR for d in diags):
        raise typer.Exit(EXIT_VALIDATION)


@flow_app.command("publish")
def publish_flow(
    flow_id: Annotated[str, typer.Argument(help="Flow id or slug")],
    bump: Annotated[str, typer.Option("--bump", help="major|minor|patch|semver")] = "patch",
    changelog: Annotated[str, typer.Option(help="Changelog entry")] = "",
    server: ServerOpt = "http://127.0.0.1:8000",
    api_key: ApiKeyOpt = None,
) -> None:
    with _client(server, api_key) as client:
        flow_id = _resolve_id(client, flow_id)
        response = _request(
            client,
            "POST",
            f"/api/v1/flows/{flow_id}/publish",
            json={"version": bump, "changelog": changelog},
        )
        response.raise_for_status()
        body = response.json()
        if not body["published"]:
            for d in body["diagnostics"]:
                err_console.print(f"[red]{d['code']}[/red] {d['message']}")
            raise typer.Exit(EXIT_VALIDATION)
        console.print(f"[green]published[/green] v{body['version']['semver']}")


@flow_app.command("run")
def run_flow_cmd(
    ref: Annotated[str, typer.Argument(help="FlowSpec path (with --local) or flow id/slug")],
    input: Annotated[str, typer.Option("--input", help="Input text")] = "",
    data: Annotated[str | None, typer.Option(help="JSON data payload")] = None,
    session: Annotated[str | None, typer.Option(help="Session/thread id")] = None,
    stream: Annotated[bool, typer.Option("--stream", help="Stream events (server mode)")] = False,
    local: Annotated[
        bool, typer.Option("--local", help="In-process compile+run, no server")
    ] = False,
    server: ServerOpt = "http://127.0.0.1:8000",
    api_key: ApiKeyOpt = None,
) -> None:
    payload_data = json.loads(data) if data else None
    if local:
        from lga.runtime import arun_flow

        result = run_async(
            arun_flow(
                json.loads(Path(ref).read_text(encoding="utf-8")),
                input_text=input,
                data=payload_data,
                session_id=session,
            )
        )
        console.print(f"status: [bold]{result.status}[/bold]")
        if result.result_text:
            print(result.result_text)
        if result.interrupt:
            console.print(f"[yellow]interrupt:[/yellow] {json.dumps(result.interrupt)}")
        if result.status == "failed":
            err_console.print(f"[red]{result.error_code}[/red] {result.error_message}")
            raise typer.Exit(1)
        return
    with _client(server, api_key) as client:
        flow_id = _resolve_id(client, ref)
        body = {
            "input_text": input,
            "data": payload_data,
            "session_id": session,
            "stream": stream,
        }
        if stream:
            with client.stream(
                "POST", f"/api/v1/flows/{flow_id}/run", json=body, timeout=None
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        print(line[5:].strip())
            return
        response = _request(client, "POST", f"/api/v1/flows/{flow_id}/run", json=body)
        response.raise_for_status()
        result = response.json()
        console.print(f"status: [bold]{result['status']}[/bold]")
        if result.get("result_text"):
            print(result["result_text"])
