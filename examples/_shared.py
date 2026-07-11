"""Shared helpers for example tests — sync wrappers, in-process app, no API keys."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def load_flow(example_dir: str | Path) -> dict[str, Any]:
    return json.loads((Path(example_dir) / "flow.json").read_text(encoding="utf-8"))


def validate_ok(spec: dict[str, Any]) -> None:
    from langgraph_agent_builder.compiler import compile_flow

    compiled = compile_flow(spec, use_cache=False)
    errors = [d for d in compiled.diagnostics if d.severity == "error"]
    assert not errors, [f"{d.code}: {d.message}" for d in errors]


def run_local(spec: dict[str, Any], input_text: str = "hi", resume: Any = None,
              session_id: str | None = None):
    from langgraph_agent_builder.runtime import arun_flow

    saver_holder: dict[str, Any] = {}

    async def _run():
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = saver_holder.setdefault("saver", InMemorySaver())
        return await arun_flow(
            spec, input_text=input_text, resume=resume,
            session_id=session_id, checkpointer=checkpointer,
        )

    return asyncio.run(_run())


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LiveServer:
    """In-process lab server on a real port (for A2A/MCP network clients)."""

    def __init__(self) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self._server = None
        self._task = None

    async def __aenter__(self) -> "LiveServer":
        import uvicorn

        from langgraph_agent_builder.app import create_app
        from langgraph_agent_builder.db.migrate import upgrade_async
        from langgraph_agent_builder.services.settings import Settings

        settings = Settings(
            home=Path(tempfile.mkdtemp(prefix="lab-example-")),
            env="test",
            port=self.port,
            host_url=self.base,
        )
        settings.ensure_dirs()
        await upgrade_async(settings)
        app = create_app(settings, backend_only=True)
        app.state.auto_migrate = False
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error")
        self._server = uvicorn.Server(config)
        self._task = asyncio.get_running_loop().create_task(self._server.serve())
        for _ in range(100):
            if self._server.started:
                break
            await asyncio.sleep(0.05)
        assert self._server.started
        return self

    async def __aexit__(self, *exc) -> None:
        self._server.should_exit = True
        await asyncio.wait_for(self._task, timeout=10)

    async def publish(self, spec: dict[str, Any]) -> str:
        import httpx

        async with httpx.AsyncClient(base_url=self.base, timeout=30) as client:
            response = await client.post("/api/v1/flows", json={"spec": spec})
            assert response.status_code == 201, response.text
            flow_id = response.json()["id"]
            response = await client.post(
                f"/api/v1/flows/{flow_id}/publish", json={"version": "minor"}
            )
            assert response.json()["published"], response.text
            return flow_id


def rpc(method: str, params: dict[str, Any], id: Any = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params}


def text_message(text: str, **extra: Any) -> dict[str, Any]:
    return {"role": "user", "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": text}], **extra}
