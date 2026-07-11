"""Unit tests for `lab flow` HTTP plumbing (SPEC §2.6).

`_check` maps HTTP failures to styled messages + exit codes; the commands pass
slugs straight to the slug-first routes (§9) and use the server-side import
upsert (§9.1) instead of a client-side GET-all fallback.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import typer
from typer.testing import CliRunner

from langgraph_agent_builder.cli._common import EXIT_CONNECTION, EXIT_ERROR, EXIT_VALIDATION
from langgraph_agent_builder.cli.flow import _check
from langgraph_agent_builder.cli.main import app

runner = CliRunner()


# --------------------------------------------------------------------------- _check
def test_check_passes_through_success() -> None:
    resp = httpx.Response(200, json={"ok": True})
    assert _check(resp) is resp


def test_check_maps_auth_to_connection_exit() -> None:
    for status in (401, 403):
        with pytest.raises(typer.Exit) as exc:
            _check(httpx.Response(status, json={"detail": "bad key"}))
        assert exc.value.exit_code == EXIT_CONNECTION


def test_check_maps_422_to_validation_exit() -> None:
    with pytest.raises(typer.Exit) as exc:
        _check(httpx.Response(422, json={"detail": "invalid FlowSpec: boom"}))
    assert exc.value.exit_code == EXIT_VALIDATION


def test_check_maps_other_errors_to_error_exit() -> None:
    for status in (404, 409, 500):
        with pytest.raises(typer.Exit) as exc:
            _check(httpx.Response(status, json={"detail": "nope"}))
        assert exc.value.exit_code == EXIT_ERROR


def test_check_tolerates_non_json_body() -> None:
    with pytest.raises(typer.Exit) as exc:
        _check(httpx.Response(500, text="Internal Server Error"))
    assert exc.value.exit_code == EXIT_ERROR


# --------------------------------------------------------------------------- commands
def _mock_server(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
    sink: list[httpx.Request],
) -> None:
    def wrapped(request: httpx.Request) -> httpx.Response:
        sink.append(request)
        return handler(request)

    def fake_client(server: str, api_key: str | None) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(wrapped), base_url="http://t")

    monkeypatch.setattr("langgraph_agent_builder.cli.flow._client", fake_client)


def test_flow_import_uses_server_upsert(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sink: list[httpx.Request] = []
    _mock_server(
        monkeypatch,
        lambda request: httpx.Response(201, json={"id": "f1", "slug": "demo"}),
        sink,
    )
    spec_path = tmp_path / "flow.json"
    spec_path.write_text('{"flow": {"slug": "demo"}}', encoding="utf-8")
    result = runner.invoke(app, ["flow", "import", str(spec_path)])
    assert result.exit_code == 0, result.output
    assert len(sink) == 1  # one POST — no GET-all/PATCH fallback round-trips
    assert json.loads(sink[0].content) == {"spec": {"flow": {"slug": "demo"}}, "upsert": True}


def test_flow_export_passes_slug_to_route(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: list[httpx.Request] = []
    _mock_server(monkeypatch, lambda request: httpx.Response(200, json={"flow": {}}), sink)
    result = runner.invoke(app, ["flow", "export", "my-slug"])
    assert result.exit_code == 0, result.output
    assert sink[0].url.path == "/api/v1/flows/my-slug/export"


def test_flow_export_not_found_prints_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_server(
        monkeypatch,
        lambda request: httpx.Response(404, json={"detail": "flow 'nope' not found"}),
        [],
    )
    result = runner.invoke(app, ["flow", "export", "nope"])
    assert result.exit_code == EXIT_ERROR
    assert "flow 'nope' not found" in result.stderr


def test_flow_run_stream_maps_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_server(
        monkeypatch,
        lambda request: httpx.Response(404, json={"detail": "flow 'gone' not found"}),
        [],
    )
    result = runner.invoke(app, ["flow", "run", "gone", "--stream"])
    assert result.exit_code == EXIT_ERROR
    assert "flow 'gone' not found" in result.stderr
