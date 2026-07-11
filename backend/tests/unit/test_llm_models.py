"""Provider-agnostic model resolution — SPEC §1.5-5.

Covers ``langgraph_agent_builder.components.llm._models``: keyless ``fake``/``echo`` providers that
keep flows testable, the shorthand/dict/invalid parsing of model values, the
``ValueError`` for unknown providers, and ``ProviderNotInstalledError`` when an
optional provider extra is missing (simulated by shadowing its import).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from langgraph_agent_builder.components.llm._models import (
    ProviderNotInstalledError,
    parse_model_value,
    resolve_embeddings,
    resolve_model,
)

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage


# --------------------------------------------------------------- parse_model_value
def test_parse_shorthand_string_splits_provider_and_model() -> None:
    assert parse_model_value("openai:gpt-4o-mini") == {
        "provider": "openai",
        "model": "gpt-4o-mini",
    }


def test_parse_shorthand_without_colon_leaves_model_empty() -> None:
    assert parse_model_value("fake") == {"provider": "fake", "model": ""}


def test_parse_dict_is_copied_not_aliased() -> None:
    source = {"provider": "fake", "temperature": 0}
    parsed = parse_model_value(source)
    parsed["provider"] = "mutated"
    assert source["provider"] == "fake"  # original untouched


def test_parse_rejects_non_str_non_dict() -> None:
    with pytest.raises(ValueError, match="unsupported model value"):
        parse_model_value(42)


# --------------------------------------------------------------- fake provider
def test_resolve_fake_uses_configured_replies_in_order() -> None:
    model = resolve_model({"provider": "fake", "replies": ["first", "second"]})
    assert model.invoke([HumanMessage(content="a")]).content == "first"
    assert model.invoke([HumanMessage(content="b")]).content == "second"


def test_resolve_fake_falls_back_to_model_string_reply() -> None:
    model = resolve_model("fake:canned-answer")
    assert model.invoke([HumanMessage(content="anything")]).content == "canned-answer"


def test_resolve_fake_default_reply_when_nothing_configured() -> None:
    model = resolve_model({"provider": "fake"})
    assert model.invoke([HumanMessage(content="x")]).content == "fake reply"


# --------------------------------------------------------------- echo provider
def test_resolve_echo_echoes_last_human_message_with_prefix() -> None:
    model = resolve_model({"provider": "echo", "model": "BOT"})
    messages: list[BaseMessage] = [
        SystemMessage(content="be terse"),
        HumanMessage(content="hello there"),
    ]
    assert model.invoke(messages).content == "BOT: hello there"


def test_resolve_echo_without_prefix_returns_bare_message() -> None:
    model = resolve_model({"provider": "echo"})
    assert model.invoke([HumanMessage(content="ping")]).content == "ping"


def test_resolve_echo_with_no_human_message_yields_empty() -> None:
    model = resolve_model("echo:")
    assert model.invoke([SystemMessage(content="only system")]).content == ""


# --------------------------------------------------------------- unknown provider
def test_resolve_model_unknown_provider_raises_valueerror() -> None:
    with pytest.raises(ValueError, match="unknown model provider 'bogus'"):
        resolve_model({"provider": "bogus", "model": "x"})


# --------------------------------------------------------------- openai construction
def test_resolve_openai_applies_kwargs_offline() -> None:
    # Construction is lazy (no network); base_url + temperature + api_key branches.
    model = resolve_model(
        {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0,
            "api_key": "sk-test-not-a-real-key",
            "base_url": "http://localhost:1234/v1",
        }
    )
    assert type(model).__name__ == "ChatOpenAI"
    assert getattr(model, "model_name") == "gpt-4o-mini"  # noqa: B009
    assert getattr(model, "temperature") == 0  # noqa: B009


def test_resolve_openai_without_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-env-key")
    model = resolve_model({"provider": "openai", "model": "gpt-4o"})
    assert type(model).__name__ == "ChatOpenAI"
    assert getattr(model, "model_name") == "gpt-4o"  # noqa: B009


# --------------------------------------------------------------- provider not installed
def test_resolve_model_openai_missing_extra_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Shadow the optional dependency so its import raises ImportError.
    monkeypatch.setitem(sys.modules, "langchain_openai", None)
    with pytest.raises(ProviderNotInstalledError, match=r"langgraph-agent-builder\[openai\]"):
        resolve_model({"provider": "openai", "model": "gpt-4o-mini"})


def test_resolve_model_anthropic_not_installed_raises() -> None:
    # langchain_anthropic is genuinely absent on this box.
    with pytest.raises(ProviderNotInstalledError, match=r"langgraph-agent-builder\[anthropic\]"):
        resolve_model({"provider": "anthropic", "model": "claude-3"})


def test_resolve_model_ollama_not_installed_raises() -> None:
    with pytest.raises(ProviderNotInstalledError, match=r"langgraph-agent-builder\[ollama\]"):
        resolve_model({"provider": "ollama", "model": "llama3", "base_url": "http://x"})


def test_provider_not_installed_error_is_runtime_error() -> None:
    from langgraph_agent_builder.errors import LabRuntimeError

    err = ProviderNotInstalledError("openai", "openai")
    assert isinstance(err, LabRuntimeError)
    assert "not installed" in str(err)


# --------------------------------------------------------------- port secrets
def test_stash_port_secret_round_trip() -> None:
    from langgraph_agent_builder.components.llm._models import stash_port_secret

    ref = stash_port_secret("flow:node:api_key", "sk-not-a-real-key")
    assert ref == {"$port_secret": "flow:node:api_key"}
    model = resolve_model({"provider": "openai", "model": "gpt-4o", "api_key": ref})
    key = getattr(model, "openai_api_key")  # noqa: B009
    assert key.get_secret_value() == "sk-not-a-real-key"


def test_unknown_port_secret_ref_raises_clear_error() -> None:
    from langgraph_agent_builder.errors import LabRuntimeError

    with pytest.raises(LabRuntimeError, match="not available in this process"):
        resolve_model({"provider": "fake", "api_key": {"$port_secret": "gone:after:restart"}})


# --------------------------------------------------------------- embeddings
def test_resolve_fake_embeddings_returns_fixed_dimension() -> None:
    emb = resolve_embeddings({"provider": "fake", "dim": 16})
    vector = emb.embed_query("hello")
    assert len(vector) == 16


@pytest.mark.parametrize("provider", ["fake", "hash", "testing"])
def test_resolve_embeddings_deterministic_aliases(provider: str) -> None:
    emb = resolve_embeddings({"provider": provider})
    # deterministic: same text -> identical vector, default size 32
    assert emb.embed_query("same") == emb.embed_query("same")
    assert len(emb.embed_query("same")) == 32


def test_resolve_embeddings_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="unknown embedding provider 'nope'"):
        resolve_embeddings({"provider": "nope"})


def test_resolve_openai_embeddings_missing_extra_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "langchain_openai", None)
    with pytest.raises(ProviderNotInstalledError, match=r"langgraph-agent-builder\[openai\]"):
        resolve_embeddings({"provider": "openai", "model": "text-embedding-3-small"})


def test_resolve_openai_embeddings_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-env-key")
    emb = resolve_embeddings({"provider": "openai", "model": "text-embedding-3-small"})
    assert type(emb).__name__ == "OpenAIEmbeddings"
    assert getattr(emb, "model") == "text-embedding-3-small"  # noqa: B009


def test_resolve_openai_embeddings_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-env-key")
    emb = resolve_embeddings({"provider": "openai"})
    assert getattr(emb, "model") == "text-embedding-3-small"  # noqa: B009  # default id


def test_resolve_ollama_embeddings_not_installed_raises() -> None:
    with pytest.raises(ProviderNotInstalledError, match=r"langgraph-agent-builder\[ollama\]"):
        resolve_embeddings({"provider": "ollama", "model": "nomic-embed"})
