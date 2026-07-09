"""Language Model — Langflow-parity dual-role component (SPEC §18).

One component, two roles (like Langflow's unified `Language Model`):

* **Model Response** — wire an ``Input`` message in and it *runs* the model,
  emitting the reply on the ``message``/``text`` ports (Chat Input → Language
  Model → Chat Output).
* **Language Model handle** — the ``model`` port always carries the provider
  *config dict* (not a client instance) so it serializes cleanly into
  checkpoints; an Agent/Router consumes it and resolves it lazily.

The node only calls the model when an ``input`` is actually connected, so the
handle-only use (feed the ``model`` port to an Agent) stays a cheap config
pass-through — no wasted completion.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from lga.sdk import Component, Output, fields, ports
from lga.sdk.component import BuildContext, NodeFn
from lga.sdk.runtime import get_run_context
from lga.sdk.templating import message_text


class LanguageModel(Component):
    component_id = "lga.llm.language_model"
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
        from lga.components.llm._models import parse_model_value, resolve_model

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            value = parse_model_value(ctx.get_field("model") or {})
            if ctx.get_field("temperature") is not None:
                value["temperature"] = ctx.get_field("temperature")
            if ctx.get_field("api_key"):
                value["api_key"] = str(ctx.get_field("api_key"))
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

            text = ""
            if ctx.get_field("stream_tokens"):
                async for chunk in model.astream(messages):
                    delta = chunk.content if isinstance(chunk.content, str) else ""
                    if delta:
                        text += delta
                        rc.stream_writer(delta)
            else:
                response = await model.ainvoke(messages)
                text = (
                    response.content if isinstance(response.content, str) else str(response.content)
                )

            out["message"] = ports.Message(role="assistant", content=text)
            out["text"] = text
            out["messages"] = [AIMessage(content=text)]
            return out

        return node
