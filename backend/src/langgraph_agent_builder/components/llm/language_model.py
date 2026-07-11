"""Language Model — Langflow-parity dual-role component (SPEC §18).

One component, two roles (like Langflow's unified `Language Model`):

* **Model Response** — wire an ``Input`` message in and it *runs* the model,
  emitting the reply on the ``message``/``text`` ports (Chat Input → Language
  Model → Chat Output).
* **Language Model handle** — the ``model`` port always carries the provider
  *config dict* (not a client instance) so it serializes cleanly into
  checkpoints; an Agent/Router consumes it and resolves it lazily. A configured
  ``api_key`` travels as an opaque ``{"$port_secret": token}`` ref — the
  plaintext stays in the process-local stash (SPEC §10.5), never in checkpoints.

The node only calls the model when an ``input`` is actually connected, so the
handle-only use (feed the ``model`` port to an Agent) stays a cheap config
pass-through — no wasted completion.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from langgraph_agent_builder.sdk import Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import BuildContext, NodeFn
from langgraph_agent_builder.sdk.runtime import get_run_context
from langgraph_agent_builder.sdk.templating import message_text


class LanguageModel(Component):
    component_id = "lab.llm.language_model"
    legacy = True
    display_name = "Language Model"
    description = (
        "Runs a language model for a given provider. Wire Input → Model Response, "
        "or feed the Language Model port to an Agent/Router."
    )
    icon = "brain-circuit"
    category = "llm"
    priority = 2

    inputs = [
        fields.ModelInput(name="model", display_name="Model", required=True),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
        fields.MultilineInput(
            name="system_message",
            display_name="System Message",
            info="Sets the assistant's behavior (used only when an Input is wired).",
        ),
        fields.SliderInput(
            name="temperature",
            display_name="Temperature",
            min=0.0,
            max=2.0,
            step=0.1,
            default=0.0,
            advanced=True,
        ),
        fields.SecretInput(
            name="api_key",
            display_name="API Key",
            info="Optional override; usually use provider env vars or a stored credential.",
            advanced=True,
        ),
        fields.BoolInput(
            name="stream_tokens", display_name="Stream Tokens", default=True, advanced=True
        ),
    ]
    outputs = [
        Output(name="message", display_name="Model Response", port=ports.MESSAGE),
        Output(name="text", display_name="Text", port=ports.TEXT),
        Output(name="model", display_name="Language Model", port=ports.LANGUAGE_MODEL),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        from langgraph_agent_builder.components.llm._models import (
            parse_model_value,
            resolve_model,
            stash_port_secret,
            stream_completion,
        )

        # Stash the resolved key at build time: the MODEL port payload is
        # checkpointed, so it carries only an opaque ref, never the plaintext.
        api_key_ref: dict[str, str] | None = None
        api_key = ctx.get_field("api_key")
        if api_key:
            from langgraph_agent_builder.schema.scrub import register_secret

            register_secret(str(api_key))
            api_key_ref = stash_port_secret(f"{ctx.flow_id}:{ctx.node_id}:api_key", str(api_key))

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            value = parse_model_value(ctx.get_field("model") or {})
            if ctx.get_field("temperature") is not None:
                value["temperature"] = ctx.get_field("temperature")
            if api_key_ref is not None:
                value["api_key"] = dict(api_key_ref)
            # The MODEL handle is always available (cheap config pass-through).
            out: dict[str, Any] = {"model": value}

            # Runner role: only when an Input message is actually wired in.
            input_value = ctx.get_input(state, "input")
            if input_value is None:
                return out

            rc = get_run_context(config)
            prompt = message_text(input_value)
            model = resolve_model(value)
            messages: list[Any] = []
            system = ctx.get_field("system_message")
            if system:
                messages.append(SystemMessage(content=str(system)))
            messages.append(HumanMessage(content=prompt))

            text = await stream_completion(
                model, messages, rc, bool(ctx.get_field("stream_tokens"))
            )

            out["message"] = ports.Message(role="assistant", content=text)
            out["text"] = text
            out["messages"] = [AIMessage(content=text)]
            return out

        return node
