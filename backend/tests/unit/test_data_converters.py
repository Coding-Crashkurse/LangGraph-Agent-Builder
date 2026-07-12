"""Unit tests for langgraph_agent_builder.components.data.converters: PromptTemplate."""

from __future__ import annotations

from langgraph_agent_builder.components.data.converters import PromptTemplate
from langgraph_agent_builder.sdk.ports import Message
from langgraph_agent_builder.sdk.testing import ComponentTestHarness

# --------------------------------------------------------------------------- PromptTemplate


async def test_prompt_template_renders_from_state_data() -> None:
    node = ComponentTestHarness().build(PromptTemplate, config={"template": "Hi {name}"})
    out = await node({"data": {"name": "Ada"}})
    assert out["text"] == "Hi Ada"
    assert isinstance(out["message"], Message)
    assert out["message"].role == "user"
    assert out["message"].content == "Hi Ada"


async def test_prompt_template_prefers_wired_input_over_data() -> None:
    node = ComponentTestHarness().build(
        PromptTemplate, config={"template": "Hi {name}"}, ports={"name": "Grace"}
    )
    out = await node({"data": {"name": "Ada"}})
    assert out["text"] == "Hi Grace"


async def test_prompt_template_missing_var_renders_empty() -> None:
    node = ComponentTestHarness().build(PromptTemplate, config={"template": "Hi {name}!"})
    out = await node({})
    assert out["text"] == "Hi !"
