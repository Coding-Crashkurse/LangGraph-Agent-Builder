"""Deterministic components for tests; only loaded when settings.testing
(the registry skips this module otherwise — CLAUDE.md §16)."""

import asyncio
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import Field

from graphforge.components.base import BaseComponent, BuildContext, ComponentConfig, NodeFn
from graphforge.components.registry import register
from graphforge.runtime.events import emit


class FakeLLMConfig(ComponentConfig):
    # literal default (not default_factory): pydantic only puts literals into the
    # JSON schema, and the schema default is what pre-fills the builder form
    replies: list[str] = Field(["ok"], min_length=1)
    emit_event: bool = True


@register
class FakeLLM(BaseComponent):
    name = "fake_llm"
    display_name = "Fake LLM (testing)"
    description = "Deterministic scripted replies; cycles through `replies`."
    category = "llm"
    version = 1
    config_model = FakeLLMConfig
    state_reads = ["messages"]
    state_writes = ["messages"]

    def build(self, config: FakeLLMConfig, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], _config: Any) -> dict[str, Any]:
            ai_count = sum(1 for m in state.get("messages") or [] if getattr(m, "type", "") == "ai")
            reply = config.replies[ai_count % len(config.replies)]
            if config.emit_event:
                emit("fake.thinking", {"reply_index": ai_count % len(config.replies)})
            return {"messages": [AIMessage(content=reply)]}

        return node


class SlowNodeConfig(ComponentConfig):
    seconds: float = Field(5.0, ge=0.0, le=300.0)


@register
class SlowNode(BaseComponent):
    name = "slow_node"
    display_name = "Slow Node (testing)"
    description = "Sleeps; used to test cancellation."
    category = "io"
    version = 1
    config_model = SlowNodeConfig
    state_reads = []
    state_writes = ["data"]

    def build(self, config: SlowNodeConfig, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], _config: Any) -> dict[str, Any]:
            emit("slow.start", {"seconds": config.seconds})
            await asyncio.sleep(config.seconds)
            return {"data": {"slept": config.seconds}}

        return node
