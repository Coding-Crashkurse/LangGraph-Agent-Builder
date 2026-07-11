"""Compiler intermediate representation shared by all passes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langgraph_agent_builder.schema.flowspec import EdgeSpec, FlowSpec, NodeSpec
from langgraph_agent_builder.sdk.component import BuildContext, Component, NodeKind
from langgraph_agent_builder.sdk.outputs import Output
from langgraph_agent_builder.sdk.ports import PortSpec


@dataclass
class NodeIR:
    spec: NodeSpec
    component: type[Component]
    config: dict[str, Any] = field(default_factory=dict)  # resolved: tweaks + $var/$secret
    outputs: dict[str, Output] = field(default_factory=dict)
    input_ports: dict[str, PortSpec] = field(default_factory=dict)
    migrated_from: str | None = None
    build_ctx: BuildContext | None = None  # filled in P4/P5

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def kind(self) -> NodeKind:
        return self.component.node_kind


@dataclass
class EdgeIR:
    spec: EdgeSpec
    source_port: PortSpec | None = None
    target_port: PortSpec | None = None
    coercion: str | None = None

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def kind(self) -> str:
        return self.spec.kind


@dataclass
class FlowIR:
    spec: FlowSpec
    nodes: dict[str, NodeIR] = field(default_factory=dict)
    edges: list[EdgeIR] = field(default_factory=list)

    def data_edges(self) -> list[EdgeIR]:
        return [e for e in self.edges if e.kind == "data"]

    def tool_edges(self) -> list[EdgeIR]:
        return [e for e in self.edges if e.kind == "tool"]

    def router_edges(self) -> list[EdgeIR]:
        return [e for e in self.edges if e.kind == "router"]

    def out_edges(self, node_id: str) -> list[EdgeIR]:
        return [e for e in self.edges if e.spec.source.node == node_id]

    def in_edges(self, node_id: str) -> list[EdgeIR]:
        return [e for e in self.edges if e.spec.target.node == node_id]
