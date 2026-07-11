"""Unit tests for the Language Model component (lab.llm.language_model).

The node emits the provider *config dict* on the MODEL port (never a client),
merging the widget model value with temperature/api_key overrides. The api_key
travels as an opaque ``{"$port_secret": token}`` ref — port payloads are
checkpointed, so plaintext credentials must never appear there (SPEC §10.5).
"""

from __future__ import annotations

import json
from typing import Any

from langgraph_agent_builder.components.llm._models import resolve_model
from langgraph_agent_builder.components.llm.language_model import LanguageModel
from langgraph_agent_builder.sdk.ports import Message
from langgraph_agent_builder.sdk.testing import ComponentTestHarness


async def _run(config: dict[str, Any]) -> dict[str, Any]:
    built = ComponentTestHarness().build(LanguageModel, config=config)
    return await built()


async def test_string_shorthand_splits_provider_and_model() -> None:
    result = await _run({"model": "openai:gpt-4o-mini", "temperature": 0.7})
    assert result["model"] == {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "temperature": 0.7,
    }


async def test_dict_value_carries_api_key_ref_and_zero_temperature() -> None:
    # temperature 0.0 is falsy but not None → it must still be emitted.
    result = await _run(
        {"model": {"provider": "fake", "model": "m"}, "temperature": 0.0, "api_key": "sk-secret9"}
    )
    assert result["model"]["provider"] == "fake"
    assert result["model"]["model"] == "m"
    assert result["model"]["temperature"] == 0.0
    # the port payload carries an opaque ref, never the plaintext key
    assert set(result["model"]["api_key"].keys()) == {"$port_secret"}
    assert "sk-secret9" not in json.dumps(result["model"])


async def test_empty_config_yields_empty_model_dict() -> None:
    # No model widget value, no overrides → both branches skipped.
    result = await _run({})
    assert result == {"model": {}}


async def test_api_key_ref_resolves_for_downstream_consumers() -> None:
    # A downstream Agent calls resolve_model on the port payload; the stash
    # resolves the ref back to the (str-coerced) key inside this process.
    result = await _run({"model": {"provider": "openai", "model": "gpt-4o"}, "api_key": 12345})
    model = resolve_model(result["model"])
    key = getattr(model, "openai_api_key")  # noqa: B009
    assert key.get_secret_value() == "12345"


async def test_handle_only_when_no_input_wired() -> None:
    # Dual-role: with no Input port wired the node is a pure config handle —
    # it must NOT run the model, only emit the MODEL config.
    result = await _run({"model": {"provider": "fake", "replies": ["nope"]}})
    assert result == {"model": {"provider": "fake", "replies": ["nope"]}}
    assert "message" not in result


async def test_runner_mode_non_streaming() -> None:
    # Wiring an Input flips the node into runner mode: it calls the (fake) model
    # and emits Model Response, while still exposing the MODEL handle.
    built = ComponentTestHarness().build(
        LanguageModel,
        config={"model": {"provider": "fake", "replies": ["Hallo!"]}, "stream_tokens": False},
        ports={"input": Message(role="user", content="hi there")},
    )
    result = await built()
    assert result["text"] == "Hallo!"
    assert result["message"].role == "assistant"
    assert result["message"].content == "Hallo!"
    assert result["model"]["provider"] == "fake"  # handle still emitted alongside the response


async def test_runner_mode_streaming_accumulates_tokens() -> None:
    built = ComponentTestHarness().build(
        LanguageModel,
        config={
            "model": {"provider": "fake", "replies": ["streamed reply"]},
            "stream_tokens": True,
        },
        ports={"input": Message(role="user", content="go")},
    )
    result = await built()
    assert result["text"] == "streamed reply"
    assert result["message"].content == "streamed reply"
