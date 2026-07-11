"""Compiler pipeline: FlowSpec → validated StateGraph (SPEC §5.3).

``compile_flow`` is pure and deterministic: same FlowSpec bytes + same registry
versions ⇒ identical graph & report. Results are cached by
``sha256(flowspec) + registry_fingerprint`` plus a snapshot digest of the
referenced $var/$secret values, vector-store names and tweaks — so a rotated
secret or per-run override is never served from a stale cache (constant-free
compiles only).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import All, Checkpointer
from pydantic import BaseModel, Field

from langgraph_agent_builder.compiler import emit as emit_pass
from langgraph_agent_builder.compiler import parse as parse_pass
from langgraph_agent_builder.compiler import resolve as resolve_pass
from langgraph_agent_builder.compiler import validate as validate_pass
from langgraph_agent_builder.compiler import wire as wire_pass
from langgraph_agent_builder.compiler.ir import FlowIR
from langgraph_agent_builder.compiler.resolve import EnvVariablesProvider, VariablesProvider
from langgraph_agent_builder.schema.diagnostics import Diagnostic, has_errors
from langgraph_agent_builder.schema.flowspec import FlowMeta, FlowSpec
from langgraph_agent_builder.schema.state import FlowState
from langgraph_agent_builder.sdk.component import BuildContext, NodeKind, SecretsResolver
from langgraph_agent_builder.sdk.registry import ComponentRegistry, get_registry

__all__ = [
    "CompileReport",
    "CompiledFlow",
    "build_report",
    "clear_compile_cache",
    "compile_flow",
]


class CompileReport(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    coercions: list[dict[str, str]] = Field(default_factory=list)
    channels: dict[str, str] = Field(default_factory=dict)  # edge_id → state channel
    interrupt_points: list[str] = Field(default_factory=list)
    router_tables: dict[str, dict[str, str]] = Field(default_factory=dict)
    tool_bindings: dict[str, list[str]] = Field(default_factory=dict)
    recursion_limit: int = 50
    fingerprint: str = ""

    model_config = {"json_schema_extra": {"description": "Compile report (SPEC §5.3)"}}


@dataclass
class CompiledFlow:
    spec: FlowSpec
    diagnostics: list[Diagnostic]
    report: CompileReport
    builder: StateGraph[FlowState] | None = None  # uncompiled StateGraph builder
    ir: FlowIR | None = None
    node_contexts: dict[str, BuildContext] = field(default_factory=dict)
    fingerprint: str = ""
    _plain_graph: CompiledStateGraph[FlowState] | None = None

    @property
    def ok(self) -> bool:
        return self.builder is not None and not has_errors(self.diagnostics)

    @property
    def graph(self) -> CompiledStateGraph[FlowState]:
        """Vanilla compiled LangGraph — no checkpointer, usable without lab."""
        if self.builder is None:
            raise ValueError("flow has compile errors; no graph available")
        if self._plain_graph is None:
            self._plain_graph = self.builder.compile()
        return self._plain_graph

    def compile(
        self,
        checkpointer: Checkpointer = None,
        interrupt_before: All | list[str] | None = None,
    ) -> CompiledStateGraph[FlowState]:
        """Compile with a checkpointer (runtime path; required for interrupts)."""
        if self.builder is None:
            raise ValueError("flow has compile errors; no graph available")
        kwargs: dict[str, Any] = {}
        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer
        if interrupt_before is not None:
            kwargs["interrupt_before"] = interrupt_before
        return self.builder.compile(**kwargs)


_cache: dict[str, CompiledFlow] = {}
_CACHE_MAX = 256


def clear_compile_cache() -> None:
    _cache.clear()


def build_report(ir: FlowIR, contexts: dict[str, BuildContext], fingerprint: str) -> CompileReport:
    """Compile report from a (possibly pruned, §6.4) IR + node contexts."""
    providers = emit_pass.pure_tool_providers(ir)
    return CompileReport(
        nodes=[
            {
                "id": n.id,
                "component_id": n.component.component_id,
                "version": n.component.version,
                "kind": n.kind.value,
                "graph_node": n.id not in providers,
            }
            for n in ir.nodes.values()
        ],
        coercions=[{"edge_id": e.id, "coercion": e.coercion} for e in ir.edges if e.coercion],
        channels={
            e.id: wire_pass.channel_for(e.spec.source.node, e.spec.source.output)
            for e in ir.data_edges()
        },
        interrupt_points=[n.id for n in ir.nodes.values() if n.kind == NodeKind.INTERRUPT],
        router_tables=_router_tables(ir),
        tool_bindings={
            n.id: [t.name for t in contexts[n.id].tools if hasattr(t, "name")]
            for n in ir.nodes.values()
            if contexts.get(n.id) and contexts[n.id].tools
        },
        recursion_limit=ir.spec.flow.settings.recursion_limit,
        fingerprint=fingerprint,
    )


def _router_tables(ir: FlowIR) -> dict[str, dict[str, str]]:
    tables: dict[str, dict[str, str]] = {}
    for e in ir.router_edges():
        tables.setdefault(e.spec.source.node, {})[e.spec.source.output] = e.spec.target.node
    return tables


def compile_flow(
    source: FlowSpec | dict[str, Any] | str | Path,
    *,
    registry: ComponentRegistry | None = None,
    variables: VariablesProvider | None = None,
    secrets: SecretsResolver | None = None,
    tweaks: dict[str, dict[str, Any]] | None = None,
    constants: dict[str, dict[str, Any]] | None = None,
    settings: Any = None,
    vectorstore_names: set[str] | None = None,
    use_cache: bool = True,
    stop_after: Literal["validate"] | None = None,
) -> CompiledFlow:
    """Compile ``source``; ``stop_after="validate"`` returns after P3 with
    diagnostics only — no component code (build()) is ever executed."""
    registry = registry or get_registry()
    variables = variables or EnvVariablesProvider()

    # P1 parse
    spec, diagnostics = parse_pass.parse(source)
    if spec is None:
        return CompiledFlow(
            spec=FlowSpec(flow=FlowMeta(name="invalid", slug="invalid")),
            diagnostics=diagnostics,
            report=CompileReport(),
        )

    fingerprint = hashlib.sha256(
        (spec.canonical_json() + registry.fingerprint()).encode()
    ).hexdigest()[:16]
    cacheable = use_cache and not constants and stop_after is None
    cache_key = ""
    if cacheable:
        cache_key = fingerprint + resolve_pass.snapshot_digest(
            spec, variables, tweaks, vectorstore_names
        )
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    # P2 resolve
    ir, d2 = resolve_pass.resolve(
        spec, registry, variables, tweaks=tweaks, vectorstore_names=vectorstore_names
    )
    diagnostics += d2

    # P3 validate
    diagnostics += validate_pass.validate(ir)
    if has_errors(diagnostics) or stop_after == "validate":
        return CompiledFlow(
            spec=spec,
            diagnostics=diagnostics,
            report=CompileReport(fingerprint=fingerprint),
            ir=ir,
        )

    # P4 wire
    contexts = wire_pass.wire(
        ir,
        secrets=secrets,
        constants=constants,
        registry=registry,
        settings=settings,
    )

    # P5 emit (build() failures → E015 diagnostics, no builder)
    builder, d5 = emit_pass.emit(ir, contexts)
    diagnostics += d5
    if builder is None:
        return CompiledFlow(
            spec=spec,
            diagnostics=diagnostics,
            report=CompileReport(fingerprint=fingerprint),
            ir=ir,
            node_contexts=contexts,
            fingerprint=fingerprint,
        )

    compiled = CompiledFlow(
        spec=spec,
        diagnostics=diagnostics,
        report=build_report(ir, contexts, fingerprint),
        builder=builder,
        ir=ir,
        node_contexts=contexts,
        fingerprint=fingerprint,
    )
    if cacheable:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[cache_key] = compiled
    return compiled


def validate_flow(
    source: FlowSpec | dict[str, Any] | str | Path,
    *,
    registry: ComponentRegistry | None = None,
    variables: VariablesProvider | None = None,
) -> list[Diagnostic]:
    """Validation-only entry (used by /validate and `lab flow validate`):
    stops after P3, so component build() code never runs."""
    return compile_flow(
        source,
        registry=registry,
        variables=variables,
        use_cache=False,
        stop_after="validate",
    ).diagnostics
