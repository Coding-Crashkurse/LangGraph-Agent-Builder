"""ComponentTestHarness (SPEC §4.10)."""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.sdk.component import (
    BuildContext,
    Component,
    InputBinding,
    NodeConfig,
    NodeFn,
    SecretsResolver,
)
from langgraph_agent_builder.sdk.ports import ToolDef


class BuiltNode:
    """A NodeFn plus its BuildContext, invokable directly in tests."""

    def __init__(self, fn: NodeFn, ctx: BuildContext) -> None:
        self.fn = fn
        self.ctx = ctx

    async def __call__(
        self,
        state: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self.fn(state or {}, config or {"configurable": {}})


class ComponentTestHarness:
    def render_descriptor(self, component: type[Component]) -> dict[str, Any]:
        """Golden-snapshot the JSON descriptor."""
        return component.descriptor()

    def build(
        self,
        component: type[Component],
        config: NodeConfig | None = None,
        secrets: dict[str, str] | None = None,
        ports: dict[str, Any] | None = None,
        tools: list[ToolDef] | None = None,
        node_id: str = "under_test",
    ) -> BuiltNode:
        """Build the NodeFn with a stub context; `ports` maps input name → value."""
        cfg = dict(config or {})
        bindings = {
            name: InputBinding(input_name=name, channel=None, constant=value)
            for name, value in (ports or {}).items()
        }
        ctx = BuildContext(
            node_id=node_id,
            flow_id="test-flow",
            label=component.display_name or node_id,
            config=cfg,
            fields=component.field_map(),
            secrets=SecretsResolver(secrets or {}),
            input_bindings=bindings,
            tools=tools or [],
        )
        instance = component()
        return BuiltNode(instance.build(ctx), ctx)

    async def run_in_flow(
        self,
        component: type[Component],
        config: NodeConfig | None = None,
        upstream: dict[str, Any] | None = None,
        input_text: str = "hi",
    ) -> dict[str, Any]:
        """Micro-flow (start → node → end) through the real compiler.

        `upstream` maps the node's input names to literal values injected via a
        Set Data-style shim; catches wiring bugs the stub context cannot.
        """
        from langgraph_agent_builder.compiler import compile_flow
        from langgraph_agent_builder.runtime.executor import run_compiled_once

        node_cfg = dict(config or {})
        spec: dict[str, Any] = {
            "schema_version": "1",
            "flow": {"name": "harness", "slug": "harness", "description": "harness"},
            "nodes": [
                {
                    "id": "start",
                    "component_id": "lab.io.start",
                    "component_version": "1.0.0",
                    "config": {},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "id": "under_test",
                    "component_id": component.component_id,
                    "component_version": component.version,
                    "config": node_cfg,
                    "position": {"x": 300, "y": 0},
                },
                {
                    "id": "end",
                    "component_id": "lab.io.end",
                    "component_version": "1.0.0",
                    "config": {},
                    "position": {"x": 600, "y": 0},
                },
            ],
            "edges": [],
        }
        edges: list[dict[str, Any]] = []
        input_ports = component.input_ports_for_config(node_cfg)
        # wire start.message into the first MESSAGE/DATA input if present
        for name, port in input_ports.items():
            if upstream and name in upstream:
                continue
            if port.family.value in ("MESSAGE", "DATA"):
                edges.append(
                    {
                        "id": f"e_start_{name}",
                        "kind": "data",
                        "source": {"node": "start", "output": "message"},
                        "target": {"node": "under_test", "input": name},
                    }
                )
                break
        outs = component.outputs_for_config(node_cfg)
        if outs:
            edges.append(
                {
                    "id": "e_out",
                    "kind": "data",
                    "source": {"node": "under_test", "output": outs[0].name},
                    "target": {"node": "end", "input": "message"},
                }
            )
        spec["edges"] = edges
        compiled = compile_flow(spec, constants={"under_test": upstream or {}})
        return await run_compiled_once(compiled, input_text=input_text)
