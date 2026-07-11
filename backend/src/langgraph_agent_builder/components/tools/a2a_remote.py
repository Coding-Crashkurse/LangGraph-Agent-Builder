"""A2A Remote Agent — consume other A2A agents from flows (SPEC §7.12).

Node mode: sends the conversation tail; remote `input-required` propagates as
our own interrupt (nested HITL across agents). Tool mode: exposed to agents as
`call_{remote_slug}`.
"""

from __future__ import annotations

import hashlib
from typing import Any, cast

import httpx
from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from lga.sdk import BuildContext, Component, Output, fields, ports
from lga.sdk.component import NodeConfig, NodeFn
from lga.sdk.ports import LazyToolset, ToolDef
from lga.sdk.runtime import get_run_context
from lga.sdk.templating import last_message_text

# process cache: (thread_id, node_id) → pending remote session
_REMOTE_SESSIONS: dict[tuple[str, str], dict[str, Any]] = {}


def _det_message_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


async def _rpc(
    client: httpx.AsyncClient, url: str, method: str, params: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        raise RuntimeError(
            f"remote A2A error {body['error'].get('code')}: {body['error'].get('message')}"
        )
    return body.get("result") or {}


def _task_text(task: dict[str, Any]) -> str:
    for artifact in task.get("artifacts") or []:
        for part in artifact.get("parts") or []:
            if part.get("kind") == "text":
                return cast(str, part["text"])
    message = (task.get("status") or {}).get("message") or {}
    for part in message.get("parts") or []:
        if part.get("kind") == "text":
            return cast(str, part["text"])
    return ""


def _interrupt_payload(task: dict[str, Any], agent_url: str) -> dict[str, Any]:
    message = (task.get("status") or {}).get("message") or {}
    prompt = ""
    data: dict[str, Any] = {}
    for part in message.get("parts") or []:
        if part.get("kind") == "text" and not prompt:
            prompt = part["text"]
        elif part.get("kind") == "data":
            data = part.get("data") or {}
    payload = dict(data) if isinstance(data, dict) else {}
    payload.setdefault("kind", "free_text")
    payload["prompt"] = prompt or payload.get("prompt") or "remote agent needs input"
    payload["remote"] = {
        "agent_url": agent_url,
        "task_id": task.get("id"),
        "context_id": task.get("contextId"),
    }
    return payload


class A2ARemoteAgent(Component):
    component_id = "lga.tools.a2a_remote_agent"
    display_name = "A2A Remote Agent"
    description = "Call another A2A agent as a node or as a tool; nested HITL propagates."
    icon = "satellite"
    category = "tools"

    inputs = [
        fields.StrInput(
            name="agent_url",
            display_name="Agent URL",
            info="Base URL of the remote agent (its card lives at /.well-known/agent-card.json).",
            required=True,
            real_time_refresh=True,
        ),
        fields.SecretInput(name="auth", display_name="API Key", advanced=True),
        fields.TabInput(name="mode", display_name="Mode", options=["node", "tool"], default="node"),
        fields.FloatInput(
            name="timeout_s", display_name="Timeout (s)", default=120.0, advanced=True
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [Output(name="message", display_name="Message", port=ports.MESSAGE)]

    @classmethod
    def outputs_for_config(cls, config: NodeConfig) -> list[Output]:
        """mode=node → Message output; mode=tool → Toolset output (SPEC §7.12)."""
        if str(config.get("mode") or "node") == "tool":
            from lga.sdk.ports import TOOLSET

            return [Output(name="toolset", display_name="Toolset", port=TOOLSET)]
        return list(cls.outputs)

    # ---------------------------------------------------------------- helpers
    def _client(self, ctx: BuildContext) -> httpx.AsyncClient:
        headers: dict[str, str] = {}
        auth = ctx.get_field("auth")
        if auth:
            headers["X-API-Key"] = str(auth)
        # no follow_redirects: a redirecting endpoint fails loudly instead of
        # silently hopping to an unvalidated (possibly private) address
        return httpx.AsyncClient(
            headers=headers,
            timeout=float(ctx.get_field("timeout_s") or 120.0),
        )

    @staticmethod
    def _endpoint(ctx: BuildContext) -> str:
        url = str(ctx.get_field("agent_url") or "").rstrip("/")
        return url + "/"

    # ---------------------------------------------------------------- node mode
    def build(self, ctx: BuildContext) -> NodeFn:
        endpoint = self._endpoint(ctx)

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rc = get_run_context(config)
            key = (rc.thread_id or "local", ctx.node_id)
            remote_context = _det_message_id("ctx", *key)

            async with self._client(ctx) as client:
                session = _REMOTE_SESSIONS.get(key)
                if session is not None:
                    # resuming: forward the recorded answer to the remote task
                    answer = interrupt(session["payload"])  # returns recorded resume
                    task = await _rpc(
                        client,
                        endpoint,
                        "message/send",
                        {
                            "message": {
                                "role": "user",
                                "taskId": session["task_id"],
                                "contextId": session["context_id"],
                                "messageId": _det_message_id(
                                    "resume", session["task_id"], str(answer)
                                ),
                                "parts": [{"kind": "data", "data": answer}],
                            }
                        },
                    )
                else:
                    text = last_message_text(state)
                    inbound = ctx.get_input(state, "input")
                    if inbound is not None and hasattr(inbound, "content"):
                        text = inbound.content or text
                    task = await _rpc(
                        client,
                        endpoint,
                        "message/send",
                        {
                            "message": {
                                "role": "user",
                                "contextId": remote_context,
                                "messageId": _det_message_id("msg", remote_context, text),
                                "parts": [{"kind": "text", "text": text}],
                            }
                        },
                    )

                while True:
                    state_name = (task.get("status") or {}).get("state", "")
                    if state_name == "input-required":
                        payload = _interrupt_payload(task, endpoint)
                        _REMOTE_SESSIONS[key] = {
                            "payload": payload,
                            "task_id": task.get("id"),
                            "context_id": task.get("contextId"),
                        }
                        rc.emit("remote.input_required", {"task_id": task.get("id")})
                        answer = interrupt(payload)  # pauses OUR flow
                        task = await _rpc(
                            client,
                            endpoint,
                            "message/send",
                            {
                                "message": {
                                    "role": "user",
                                    "taskId": task.get("id"),
                                    "contextId": task.get("contextId"),
                                    "messageId": _det_message_id(
                                        "resume", str(task.get("id")), str(answer)
                                    ),
                                    "parts": [{"kind": "data", "data": answer}],
                                }
                            },
                        )
                        continue
                    if state_name in ("completed", "failed", "canceled", "rejected"):
                        _REMOTE_SESSIONS.pop(key, None)
                        break
                    # non-terminal (e.g. blocking=false server): poll
                    task = await _rpc(client, endpoint, "tasks/get", {"id": task.get("id")})

            if state_name != "completed":
                raise RuntimeError(f"remote agent task ended {state_name}")
            text = _task_text(task)
            rc.emit("remote.completed", {"task_id": task.get("id"), "preview": text[:200]})
            return {
                "message": ports.Message(role="assistant", content=text),
                "messages": [AIMessage(content=text)],
            }

        return node

    # ---------------------------------------------------------------- tool mode
    def provide_tools(self, ctx: BuildContext) -> LazyToolset:
        endpoint = self._endpoint(ctx)
        component = self

        async def factory() -> list[ToolDef]:
            async with component._client(ctx) as client:
                card = (await client.get(endpoint + ".well-known/agent-card.json")).json()
            slug = str(card.get("name", "remote")).lower().replace(" ", "_")

            async def call_remote(message: str) -> str:
                async with component._client(ctx) as client:
                    task = await _rpc(
                        client,
                        endpoint,
                        "message/send",
                        {
                            "message": {
                                "role": "user",
                                "messageId": _det_message_id("tool", endpoint, message),
                                "parts": [{"kind": "text", "text": message}],
                            }
                        },
                    )
                state_name = (task.get("status") or {}).get("state", "")
                if state_name == "input-required":
                    raise RuntimeError(
                        "remote agent requires human input — attach it as a node "
                        "(mode=node) so the interrupt can propagate"
                    )
                return _task_text(task)

            return [
                ToolDef(
                    name=f"call_{slug}",
                    description=str(card.get("description", ""))[:500],
                    args_schema={
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                    callable_ref=call_remote,
                )
            ]

        return LazyToolset(factory)
