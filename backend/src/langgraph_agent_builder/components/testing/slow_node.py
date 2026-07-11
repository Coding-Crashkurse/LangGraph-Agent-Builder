"""Slow Node — sleeps in 100ms slices, observing cancellation (SPEC §12.7)."""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph_agent_builder.sdk import BuildContext, Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import NodeFn
from langgraph_agent_builder.sdk.runtime import get_run_context


class SlowNode(Component):
    component_id = "lab.testing.slow_node"
    display_name = "Slow Node (testing)"
    description = "Sleeps `seconds`, checking the cancellation token every 100ms."
    icon = "timer"
    category = "testing"

    inputs = [
        fields.FloatInput(name="seconds", display_name="Seconds", default=5.0, min=0.0, max=300.0),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [Output(name="message", display_name="Message", port=ports.MESSAGE)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            rc = get_run_context(config)
            seconds = float(ctx.get_field("seconds") or 0.0)
            rc.emit_status(f"sleeping {seconds}s")
            remaining = seconds
            while remaining > 0:
                rc.raise_if_cancelled()
                await asyncio.sleep(min(0.1, remaining))
                remaining -= 0.1
            passthrough = ctx.get_input(state, "input")
            return {
                "message": passthrough
                if isinstance(passthrough, ports.Message)
                else ports.Message(role="assistant", content=f"slept {seconds}s"),
                "data": {"slept": seconds},
            }

        return node


class FailingNode(Component):
    component_id = "lab.testing.failing_node"
    display_name = "Failing Node (testing)"
    description = "Raises a configured error — exercises RT103 and A2A `failed`."
    icon = "bomb"
    category = "testing"

    inputs = [
        fields.StrInput(
            name="error_message", display_name="Error Message", default="intentional failure"
        ),
        fields.BoolInput(name="fail", display_name="Fail", default=True),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
    ]
    outputs = [Output(name="message", display_name="Message", port=ports.MESSAGE)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            if ctx.get_field("fail"):
                raise RuntimeError(str(ctx.get_field("error_message") or "intentional failure"))
            return {"message": ports.Message(role="assistant", content="did not fail")}

        return node


class EchoData(Component):
    component_id = "lab.testing.echo_data"
    display_name = "Echo Data (testing)"
    description = "Echoes its json input to output and into `data.echo`."
    icon = "copy"
    category = "testing"

    inputs = [fields.HandleField(name="input", display_name="Input", as_port=ports.JSON)]
    outputs = [Output(name="json", display_name="Json", port=ports.JSON)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            value = ctx.get_input(state, "input") or {}
            return {"json": value, "data": {"echo": value}}

        return node
