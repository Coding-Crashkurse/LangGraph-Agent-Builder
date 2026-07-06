"""Compiler pipeline: FlowSpec → validated StateGraph (SPEC §5.3).

``compile_flow`` is pure and deterministic: same FlowSpec bytes + same registry
versions ⇒ identical graph & report. Results are cached by
``sha256(flowspec) + registry_fingerprint`` (only for tweak-/constant-free compiles).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.graph import StateGraph
from pydantic import BaseModel, Field

from lga.compiler import emit as emit_pass
from lga.compiler import parse as parse_pass
from lga.compiler import resolve as resolve_pass
from lga.compiler import validate as validate_pass
from lga.compiler import wire as wire_pass
from lga.compiler.ir import FlowIR
from lga.compiler.resolve import EnvVariablesProvider, VariablesProvider
from lga.schema.diagnostics import Diagnostic, has_errors
from lga.schema.flowspec import FlowSpec
from lga.sdk.component import BuildContext, NodeKind, SecretsResolver
from lga.sdk.registry import ComponentRegistry, get_registry

__all__ = ["CompileReport", "CompiledFlow", "clear_compile_cache", "compile_flow"]


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
    builder: StateGraph | None = None  # uncompiled StateGraph builder
    ir: FlowIR | None = None
    node_contexts: dict[str, BuildContext] = field(default_factory=dict)
    fingerprint: str = ""
    _plain_graph: Any = None

    @property
    def ok(self) -> bool:
        return self.builder is not None and not has_errors(self.diagnostics)

    @property
    def graph(self):
        """Vanilla compiled LangGraph — no checkpointer, usable without lga."""
        if self.builder is None:
            raise ValueError("flow has compile errors; no graph available")
        if self._plain_graph is None:
            self._plain_graph = self.builder.compile()
        return self._plain_graph

    def compile(self, checkpointer: Any = None, interrupt_before: Any = None):
        """Compile with a checkpointer (runtime path; required for interrupts)."""
        if self.builder is None:
            raise ValueError("flow has compile errors; no graph available")
        kwargs: dict[str, Any] = {}
        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer
        if interrupt_before is not None:
            kwargs["interrupt_before"] = interrupt_before
        return self.builder.compile(**kwargs)


_cache: dict[tuple[str, str], CompiledFlow] = {}


def clear_compile_cache() -> None:
    _cache.clear()


def _report(ir: FlowIR, contexts: dict[str, BuildContext], fingerprint: str) -> CompileReport:
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
    use_cache: bool = True,
) -> CompiledFlow:
    registry = registry or get_registry()
    variables = variables or EnvVariablesProvider()

    # P1 parse
    spec, diagnostics = parse_pass.parse(source)
    if spec is None:
        return CompiledFlow(
            spec=FlowSpec(flow={"name": "invalid", "slug": "invalid"}),
            diagnostics=diagnostics,
            report=CompileReport(),
        )

    cacheable = use_cache and not tweaks and not constants
    fingerprint = hashlib.sha256(
        (spec.canonical_json() + registry.fingerprint()).encode()
    ).hexdigest()[:16]
    if cacheable and (fingerprint, registry.fingerprint()) in _cache:
        return _cache[(fingerprint, registry.fingerprint())]

    # P2 resolve
    ir, d2 = resolve_pass.resolve(spec, registry, variables, tweaks=tweaks)
    diagnostics += d2

    # P3 validate
    diagnostics += validate_pass.validate(ir)
    if has_errors(diagnostics):
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

    # P5 emit
    builder = emit_pass.emit(ir, contexts)

    compiled = CompiledFlow(
        spec=spec,
        diagnostics=diagnostics,
        report=_report(ir, contexts, fingerprint),
        builder=builder,
        ir=ir,
        node_contexts=contexts,
        fingerprint=fingerprint,
    )
    if cacheable:
        _cache[(fingerprint, registry.fingerprint())] = compiled
    return compiled


def validate_flow(
    source: FlowSpec | dict[str, Any] | str | Path,
    *,
    registry: ComponentRegistry | None = None,
    variables: VariablesProvider | None = None,
) -> list[Diagnostic]:
    """Validation-only entry (used by /validate and `lga flow validate`)."""
    return compile_flow(source, registry=registry, variables=variables, use_cache=False).diagnostics
