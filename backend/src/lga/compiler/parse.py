"""P1 parse: FlowSpec JSON → typed IR skeleton; schema violations → E0xx."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lga.schema.diagnostics import Diagnostic, DiagnosticCode
from lga.schema.flowspec import (
    RESERVED_NODE_IDS,
    FlowSpec,
    FlowSpecError,
    parse_flowspec,
)


def parse(
    source: FlowSpec | dict[str, Any] | str | Path,
) -> tuple[FlowSpec | None, list[Diagnostic]]:
    try:
        spec = parse_flowspec(source)
    except FlowSpecError as exc:
        return None, [
            Diagnostic.make(
                DiagnosticCode.E001,
                f"FlowSpec schema invalid: {exc}",
                fix_hint="Validate against schema/flowspec.schema.json.",
            )
        ]
    diagnostics: list[Diagnostic] = []
    seen: set[str] = set()
    for node in spec.nodes:
        if node.id in seen:
            diagnostics.append(
                Diagnostic.make(
                    DiagnosticCode.E003, f"duplicate node id {node.id!r}", node_id=node.id
                )
            )
        seen.add(node.id)
        if node.id in RESERVED_NODE_IDS:
            expected = f"lga.io.{node.id}"
            if node.component_id != expected:
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.E003,
                        f"reserved node id {node.id!r} must use component {expected!r}, "
                        f"got {node.component_id!r}",
                        node_id=node.id,
                    )
                )
    edge_ids: set[str] = set()
    for edge in spec.edges:
        if edge.id in edge_ids:
            diagnostics.append(
                Diagnostic.make(
                    DiagnosticCode.E001, f"duplicate edge id {edge.id!r}", edge_id=edge.id
                )
            )
        edge_ids.add(edge.id)
        for endpoint, ref in (("source", edge.source.node), ("target", edge.target.node)):
            if ref not in seen:
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.E001,
                        f"edge {edge.id!r} {endpoint} references unknown node {ref!r}",
                        edge_id=edge.id,
                    )
                )
    return spec, diagnostics
