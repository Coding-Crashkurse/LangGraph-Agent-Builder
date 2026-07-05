"""Provider-agnostic model resolution with lazy imports (SPEC §1.5-5).

Providers are optional extras; importing this module never pulls them in.
ModelInput values look like {"provider": "openai", "model": "gpt-4o-mini",
"temperature": 0} or the shorthand string "openai:gpt-4o-mini".
"""

from __future__ import annotations

from typing import Any

PROVIDERS = ("openai", "anthropic", "ollama", "fake")


class ProviderNotInstalledError(RuntimeError):
    def __init__(self, provider: str, extra: str) -> None:
        super().__init__(
            f"model provider {provider!r} is not installed — install lga[{extra}]"
        )


def parse_model_value(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        provider, _, model = value.partition(":")
        return {"provider": provider, "model": model}
    if isinstance(value, dict):
        return dict(value)
    raise ValueError(f"unsupported model value: {value!r}")


def resolve_model(value: Any):  # -> BaseChatModel
    cfg = parse_model_value(value)
    provider = str(cfg.get("provider", "")).lower()
    model = str(cfg.get("model", ""))
    kwargs: dict[str, Any] = {}
    if cfg.get("temperature") is not None:
        kwargs["temperature"] = cfg["temperature"]
    if cfg.get("api_key"):
        kwargs["api_key"] = str(cfg["api_key"])
    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ProviderNotInstalledError("openai", "openai") from exc
        if cfg.get("base_url"):
            kwargs["base_url"] = cfg["base_url"]
        return ChatOpenAI(model=model, **kwargs)
    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise ProviderNotInstalledError("anthropic", "anthropic") from exc
        return ChatAnthropic(model=model, **kwargs)
    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise ProviderNotInstalledError("ollama", "ollama") from exc
        if cfg.get("base_url"):
            kwargs["base_url"] = cfg["base_url"]
        return ChatOllama(model=model, **kwargs)
    if provider == "fake":
        # deterministic model for tests: replies with a fixed string
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        replies = cfg.get("replies") or [model or "fake reply"]
        return FakeListChatModel(responses=[str(r) for r in replies])
    raise ValueError(f"unknown model provider {provider!r} (supported: {PROVIDERS})")


def resolve_embeddings(value: Any):  # -> Embeddings
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
        return OllamaEmbeddings(model=model)
    if provider == "fake":
        from langchain_core.embeddings.fake import DeterministicFakeEmbedding

        return DeterministicFakeEmbedding(size=32)
    raise ValueError(f"unknown embedding provider {provider!r}")
