"""Provider-agnostic model resolution with lazy imports (SPEC §1.5-5).

Providers are optional extras; importing this module never pulls them in.
ModelInput values look like {"provider": "openai", "model": "gpt-4o-mini",
"temperature": 0} or the shorthand string "openai:gpt-4o-mini".
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from langgraph_agent_builder.errors import LabRuntimeError

if TYPE_CHECKING:
    from langchain_core.callbacks import CallbackManagerForLLMRun
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import ChatResult

    from langgraph_agent_builder.sdk.component import BuildContext
    from langgraph_agent_builder.sdk.runtime import RunContext

PROVIDERS = ("openai", "anthropic", "ollama", "fake", "echo")


def collect_prompt_values(
    ctx: BuildContext, state: dict[str, Any], template: str
) -> dict[str, Any]:
    """Resolve {var} values: connected port > shared data key > config field."""
    from langgraph_agent_builder.sdk.templating import PROMPT_VAR_RE

    values: dict[str, Any] = {}
    data = state.get("data") or {}
    for var in PROMPT_VAR_RE.findall(template):
        value = ctx.get_input(state, var)
        if value is None:
            value = data.get(var)
        values[var] = value
    return values


class ProviderNotInstalledError(LabRuntimeError):
    def __init__(self, provider: str, extra: str) -> None:
        super().__init__(
            f"model provider {provider!r} is not installed — "
            f"install langgraph-agent-builder[{extra}]"
        )


# ------------------------------------------------------------------ port secrets
# The LANGUAGE_MODEL port payload lands in FlowState.ports and is persisted by
# the checkpointer, so it must never carry a plaintext credential (SPEC §10.5).
# Components stash the resolved key here at build time (compile runs in the same
# process before any node executes, including on resume) and put only the opaque
# `{"$port_secret": token}` ref on the wire.
_PORT_SECRETS: dict[str, str] = {}
_PORT_SECRET_KEY = "$port_secret"


def stash_port_secret(token: str, value: str) -> dict[str, str]:
    """Store a resolved credential under *token*; returns the serializable ref."""
    _PORT_SECRETS[token] = value
    return {_PORT_SECRET_KEY: token}


def _resolve_port_secret(ref: dict[str, Any]) -> str:
    token = str(ref.get(_PORT_SECRET_KEY, ""))
    if token not in _PORT_SECRETS:
        raise LabRuntimeError(
            f"model api_key reference {token!r} is not available in this process — "
            "re-run the flow so the credential is re-resolved"
        )
    return _PORT_SECRETS[token]


# ------------------------------------------------------------------ shared plumbing
async def stream_completion(
    model: BaseChatModel, messages: list[BaseMessage], rc: RunContext, stream: bool
) -> str:
    """One completion; with *stream* the token deltas go to the run context."""
    if stream:
        text = ""
        async for chunk in model.astream(messages):
            delta = chunk.content if isinstance(chunk.content, str) else ""
            if delta:
                text += delta
                rc.stream_writer(delta)
        return text
    response = await model.ainvoke(messages)
    return response.content if isinstance(response.content, str) else str(response.content)


def parse_json_reply(text: str) -> Any:
    """Parse a model's JSON reply, tolerating ```json fences; invalid → {"raw": ...}."""
    raw = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def _echo_chat_model(prefix: str = "") -> BaseChatModel:
    """Deterministic chat model that echoes the last human message.

    Works everywhere a real model does (llm_call, llm_agent, llm_router) —
    flows stay fully testable without API keys (SPEC §1.5-6).
    """
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class EchoChatModel(BaseChatModel):
        echo_prefix: str = ""

        @property
        def _llm_type(self) -> str:
            return "lab-echo"

        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: CallbackManagerForLLMRun | None = None,
            **kw: Any,
        ) -> ChatResult:
            text = ""
            for message in reversed(messages):
                if getattr(message, "type", "") == "human":
                    content = message.content
                    text = content if isinstance(content, str) else str(content)
                    break
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content=self.echo_prefix + text))]
            )

    return EchoChatModel(echo_prefix=prefix)


def parse_model_value(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        provider, _, model = value.partition(":")
        return {"provider": provider, "model": model}
    if isinstance(value, dict):
        return dict(value)
    raise ValueError(f"unsupported model value: {value!r}")


def resolve_model(value: Any) -> BaseChatModel:
    cfg = parse_model_value(value)
    provider = str(cfg.get("provider", "")).lower()
    model = str(cfg.get("model", ""))
    kwargs: dict[str, Any] = {}
    if cfg.get("temperature") is not None:
        kwargs["temperature"] = cfg["temperature"]
    api_key = cfg.get("api_key")
    if isinstance(api_key, dict) and _PORT_SECRET_KEY in api_key:
        api_key = _resolve_port_secret(api_key)
    if api_key:
        kwargs["api_key"] = str(api_key)
    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ProviderNotInstalledError("openai", "openai") from exc
        if cfg.get("base_url"):
            kwargs["base_url"] = cfg["base_url"]
        return ChatOpenAI(model=model, **kwargs)  # type: ignore[call-arg]  # `model` is a pydantic alias langchain_openai exposes; unseen by mypy
    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise ProviderNotInstalledError("anthropic", "anthropic") from exc
        return cast("BaseChatModel", ChatAnthropic(model=model, **kwargs))
    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise ProviderNotInstalledError("ollama", "ollama") from exc
        if cfg.get("base_url"):
            kwargs["base_url"] = cfg["base_url"]
        return cast("BaseChatModel", ChatOllama(model=model, **kwargs))
    if provider == "fake":
        # deterministic model for tests: replies with a fixed string
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        replies = cfg.get("replies") or [model or "fake reply"]
        return FakeListChatModel(responses=[str(r) for r in replies])
    if provider == "echo":
        # echoes the last human message; `model` doubles as an optional prefix
        return _echo_chat_model(prefix=f"{model}: " if model else "")
    raise ValueError(f"unknown model provider {provider!r} (supported: {PROVIDERS})")


# ------------------------------------------------------------------ resource-backed models
# The Resources layer (§Resources) centralizes provider config: a node references
# a `model_provider` resource by name (ResourceRefInput → ResourceHandle), never
# by inline credentials. At build/run time the running server resolves the
# resource's config (provider/base_url/api_key with $secret/$var applied) and the
# chosen model name (carried on the handle payload) into a concrete chat model.
def _resource_handle_parts(value: Any) -> tuple[str, dict[str, Any]]:
    """Recover ``(resource_name, payload)`` from a ResourceHandle or its dict/ref
    form (the ``{"$resource": name, ...}`` widget value seen headless, or a
    serialized handle ``{"name", "resource_type", "payload"}``)."""
    from langgraph_agent_builder.sdk.ports import ResourceHandle

    if isinstance(value, ResourceHandle):
        return value.name, dict(value.payload)
    if isinstance(value, dict) and ("$resource" in value or "name" in value):
        name = str(value.get("$resource") or value.get("name") or "")
        payload = {
            k: v
            for k, v in value.items()
            if k not in ("$resource", "name", "resource_type", "payload")
        }
        nested = value.get("payload")
        if isinstance(nested, dict):
            payload.update(nested)
        return name, payload
    raise LabRuntimeError(f"expected a model_provider resource reference, got {value!r}")


async def _resolved_provider_config(name: str) -> dict[str, Any] | None:
    """The named ``model_provider`` resource's config with secrets/vars resolved,
    via the running server's ResourcesService — ``None`` headless or absent."""
    from langgraph_agent_builder.services.locator import get_services

    svc = get_services()
    if svc is None or getattr(svc, "resources", None) is None:
        return None
    result = await svc.resources.resolved_config("model_provider", name)
    return cast("dict[str, Any] | None", result)


async def resolve_model_resource(value: Any) -> BaseChatModel:
    """Build a chat model from a ``model_provider`` ResourceHandle.

    Reads the resource's config (provider/base_url/api_key/… with $secret/$var
    resolved) from the running server, folds in the model name carried on the
    handle payload, and constructs the model via :func:`resolve_model`. When
    there is no service context (headless / python export / unit tests), an
    inline ``provider`` on the handle payload is honored — so ``fake``/``echo``
    providers stay runnable without a server or network; otherwise a clear
    error names the unresolved resource."""
    name, payload = _resource_handle_parts(value)
    cfg = await _resolved_provider_config(name)
    if cfg is None:
        if payload.get("provider"):
            cfg = {k: v for k, v in payload.items() if k != "model"}
        else:
            raise LabRuntimeError(
                f"model provider resource {name!r} could not be resolved — "
                "run inside a lab server, or reference a fake/echo provider for tests"
            )
    model_cfg = dict(cfg)
    model_name = payload.get("model") or cfg.get("model")
    if model_name:  # never inject a str(None) model — echo would prefix "None: "
        model_cfg["model"] = model_name
    return resolve_model(model_cfg)


def resolve_embeddings(value: Any) -> Embeddings:
    cfg = parse_model_value(value)
    provider = str(cfg.get("provider", "")).lower()
    model = str(cfg.get("model", ""))
    if provider == "openai":
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError as exc:
            raise ProviderNotInstalledError("openai", "openai") from exc
        return OpenAIEmbeddings(model=model or "text-embedding-3-small")
    if provider == "ollama":
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError as exc:
            raise ProviderNotInstalledError("ollama", "ollama") from exc
        return cast("Embeddings", OllamaEmbeddings(model=model))
    if provider in ("fake", "hash", "testing"):
        from langchain_core.embeddings.fake import DeterministicFakeEmbedding

        return DeterministicFakeEmbedding(size=int(cfg.get("dim") or 32))
    raise ValueError(f"unknown embedding provider {provider!r}")
