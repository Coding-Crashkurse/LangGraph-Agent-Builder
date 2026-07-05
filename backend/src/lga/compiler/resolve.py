"""P2 resolve: registry lookup, migrations, tweaks, $var/$secret resolution,
field-level config validation (SPEC §5.3-P2, E002/E010/E011/E012, W30x)."""

from __future__ import annotations

from typing import Any, Protocol

import jsonschema

from lga.compiler.ir import EdgeIR, FlowIR, NodeIR
from lga.schema.diagnostics import Diagnostic, DiagnosticCode
from lga.schema.flowspec import FlowSpec
from lga.sdk.component import SecretRef
from lga.sdk.registry import ComponentRegistry


class VariablesProvider(Protocol):
    """Pre-fetched global variables & secrets; sync access during compile."""

    def get_var(self, name: str) -> str | None: ...
    def get_secret(self, name: str) -> str | None: ...
    def has_var(self, name: str) -> bool: ...
    def has_secret(self, name: str) -> bool: ...


class EnvVariablesProvider:
    """Headless default: LGA_VAR_<NAME> / LGA_CRED_<NAME> + raw env fallback for creds."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        import os

        self._env = dict(env if env is not None else os.environ)

    def get_var(self, name: str) -> str | None:
        return self._env.get(f"LGA_VAR_{name.upper()}") or self._env.get(name)

    def get_secret(self, name: str) -> str | None:
        return self._env.get(f"LGA_CRED_{name.upper()}") or self._env.get(name)

    def has_var(self, name: str) -> bool:
        return self.get_var(name) is not None

    def has_secret(self, name: str) -> bool:
        return self.get_secret(name) is not None


def _resolve_refs(
    value: Any,
    variables: VariablesProvider,
    diagnostics: list[Diagnostic],
    node_id: str,
    field: str,
) -> Any:
    """Recursively replace {"$var": name} / {"$secret": name} refs with values."""
    if isinstance(value, dict):
        if set(value.keys()) == {"$var"}:
            name = str(value["$var"])
            if not variables.has_var(name):
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.E012,
                        f"global variable {name!r} does not exist",
                        node_id=node_id,
                        field=field,
                        fix_hint="Create it under Settings → Global Variables or set "
                        f"LGA_VAR_{name.upper()}.",
                    )
                )
                return None
            return variables.get_var(name)
        if set(value.keys()) == {"$secret"}:
            name = str(value["$secret"])
            if not variables.has_secret(name):
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.E012,
                        f"secret {name!r} does not exist",
                        node_id=node_id,
                        field=field,
                        fix_hint="Create a credential variable or set "
                        f"LGA_CRED_{name.upper()}.",
                    )
                )
                return None
            return SecretRef(variables.get_secret(name) or "")
        return {
            k: _resolve_refs(v, variables, diagnostics, node_id, field) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_resolve_refs(v, variables, diagnostics, node_id, field) for v in value]
    return value


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def resolve(
    spec: FlowSpec,
    registry: ComponentRegistry,
    variables: VariablesProvider,
    tweaks: dict[str, dict[str, Any]] | None = None,
) -> tuple[FlowIR, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    ir = FlowIR(spec=spec)
    tweaks = tweaks or {}

    for node in spec.nodes:
        cls = registry.get(node.component_id)
        if cls is None:
            diagnostics.append(
                Diagnostic.make(
                    DiagnosticCode.E002,
                    f"unknown component {node.component_id!r}",
                    node_id=node.id,
                    fix_hint="Install the providing package or check LGA_COMPONENTS_PATH.",
                )
            )
            continue

        config = dict(node.config)
        migrated_from: str | None = None
        if node.component_version != cls.version:
            config = cls.migrate_config(node.component_version, config)
            migrated_from = node.component_version
            diagnostics.append(
                Diagnostic.make(
                    DiagnosticCode.W302,
                    f"component {cls.component_id} migrated "
                    f"{node.component_version} → {cls.version}",
                    node_id=node.id,
                )
            )

        # tweaks: one-time overrides, validated below like normal values (§9.4)
        for fname, fvalue in (tweaks.get(node.id) or {}).items():
            f = cls.field_map().get(fname)
            if f is None:
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.E011,
                        f"tweak targets unknown field {fname!r}",
                        node_id=node.id,
                        field=fname,
                    )
                )
                continue
            from lga.sdk.fields import SecretInput

            if isinstance(f, SecretInput):
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.E011,
                        f"secrets are not tweakable ({fname})",
                        node_id=node.id,
                        field=fname,
                    )
                )
                continue
            config[fname] = fvalue

        # $var/$secret refs → concrete values (E012 when missing)
        for fname in list(config.keys()):
            config[fname] = _resolve_refs(config[fname], variables, diagnostics, node.id, fname)

        # field-level validation (E010/E011, W301)
        field_map = cls.field_map()
        for f in cls.inputs:
            value = config.get(f.name, f.default)
            if f.deprecated and f.name in config and not _is_empty(config[f.name]):
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.W301,
                        f"field {f.name!r} is deprecated",
                        node_id=node.id,
                        field=f.name,
                    )
                )
            if _is_empty(value):
                continue  # required-ness checked in P3 (port may satisfy it)
            schema = f.json_schema()
            if schema and not isinstance(value, SecretRef):
                try:
                    jsonschema.validate(value, schema)
                except jsonschema.ValidationError as exc:
                    diagnostics.append(
                        Diagnostic.make(
                            DiagnosticCode.E011,
                            f"field {f.name!r}: {exc.message}",
                            node_id=node.id,
                            field=f.name,
                        )
                    )
        for fname in config:
            if fname not in field_map and fname not in ("tool_name", "tool_description"):
                # unknown keys are tolerated (forward compat) but never validated
                pass

        # defaults fill-in so build() sees complete config
        for f in cls.inputs:
            if f.name not in config and f.default is not None:
                config[f.name] = f.default

        node_ir = NodeIR(
            spec=node,
            component=cls,
            config=config,
            outputs={o.name: o for o in cls.outputs_for_config(config)},
            input_ports=cls.input_ports_for_config(config),
            migrated_from=migrated_from,
        )
        ir.nodes[node.id] = node_ir

    for edge in spec.edges:
        edge_ir = EdgeIR(spec=edge)
        src = ir.nodes.get(edge.source.node)
        tgt = ir.nodes.get(edge.target.node)
        if src is not None:
            out = src.outputs.get(edge.source.output)
            edge_ir.source_port = out.port if out else None
        if tgt is not None and edge.kind != "router":
            edge_ir.target_port = tgt.input_ports.get(edge.target.input)
        ir.edges.append(edge_ir)

    return ir, diagnostics
