"""P2 resolve: registry lookup, migrations, tweaks, $var/$secret resolution,
field-level config validation (SPEC §5.3-P2, E002/E010/E011/E012, W30x)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol, runtime_checkable

import jsonschema  # type: ignore[import-untyped]  # no stubs installed for jsonschema

from langgraph_agent_builder.compiler.ir import EdgeIR, FlowIR, NodeIR
from langgraph_agent_builder.schema.diagnostics import Diagnostic, DiagnosticCode
from langgraph_agent_builder.schema.flowspec import FlowSpec
from langgraph_agent_builder.sdk.component import SecretRef
from langgraph_agent_builder.sdk.fields import Field, SecretInput
from langgraph_agent_builder.sdk.registry import ComponentRegistry


class VariablesProvider(Protocol):
    """Pre-fetched global variables & secrets; sync access during compile."""

    def get_var(self, name: str) -> str | None: ...
    def get_secret(self, name: str) -> str | None: ...
    def has_var(self, name: str) -> bool: ...
    def has_secret(self, name: str) -> bool: ...


@runtime_checkable
class SupportsEnvFallback(Protocol):
    """Optional VariablesProvider extension (Settings.fallback_to_env_var):
    raw-environment lookup for $var refs missing from the snapshot."""

    def env_fallback(self, name: str) -> str | None: ...


def _env_fallback(variables: VariablesProvider, name: str) -> str | None:
    if isinstance(variables, SupportsEnvFallback):
        return variables.env_fallback(name)
    return None


class EnvVariablesProvider:
    """Headless default: LAB_VAR_<NAME> / LAB_CRED_<NAME>, each with a raw-env
    fallback (``name`` looked up verbatim when the prefixed form is absent)."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        import os

        self._env = dict(env if env is not None else os.environ)

    def get_var(self, name: str) -> str | None:
        return self._env.get(f"LAB_VAR_{name.upper()}") or self._env.get(name)

    def get_secret(self, name: str) -> str | None:
        return self._env.get(f"LAB_CRED_{name.upper()}") or self._env.get(name)

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
    vectorstore_names: set[str] | None = None,
    field_def: Field | None = None,
) -> Any:
    """Recursively replace {"$var": name} / {"$secret": name} /
    {"$vectorstore": name} refs with concrete values / handles.

    Credential-leak guard (E014, SPEC §5.4/§10.5): a {"$secret": name} ref —
    at ANY nesting depth — may only live in a Secret field, so a resolved
    credential can never flow into a plaintext/content field (LLM prompt,
    output, log); the analogue of Langflow's _reject_credential_in_non_password.
    Generic $var refs are unrestricted."""
    if isinstance(value, dict):
        if "$vectorstore" in value:
            from langgraph_agent_builder.sdk.ports import VectorStoreHandle

            name = str(value["$vectorstore"])
            if vectorstore_names is not None and name not in vectorstore_names:
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.E013,
                        f"vector store connection {name!r} does not exist",
                        node_id=node_id,
                        field=field,
                        fix_hint="Create it under Settings → Vector Stores or set "
                        f"LAB_VECTORSTORE_{name.upper().replace('-', '_')}.",
                    )
                )
                return None
            return VectorStoreHandle(connection=name, collection=value.get("collection"))
        if set(value.keys()) == {"$var"}:
            name = str(value["$var"])
            if not variables.has_var(name):
                resolved = _env_fallback(variables, name)
                if resolved is not None:
                    return resolved
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.E012,
                        f"global variable {name!r} does not exist",
                        node_id=node_id,
                        field=field,
                        fix_hint="Create it under Settings → Global Variables or set "
                        f"LAB_VAR_{name.upper()}.",
                    )
                )
                return None
            return variables.get_var(name)
        if set(value.keys()) == {"$secret"}:
            name = str(value["$secret"])
            if field_def is None or not isinstance(field_def, SecretInput):
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.E014,
                        f"credential $secret {name!r} assigned to non-credential field {field!r}",
                        node_id=node_id,
                        field=field,
                        fix_hint="Use a generic $var here, or move the value into a Secret field.",
                    )
                )
                return None
            if not variables.has_secret(name):
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.E012,
                        f"secret {name!r} does not exist",
                        node_id=node_id,
                        field=field,
                        fix_hint=f"Create a credential variable or set LAB_CRED_{name.upper()}.",
                    )
                )
                return None
            secret_value = variables.get_secret(name) or ""
            # remember the plaintext so the event/log scrubber can redact it (§10.5)
            from langgraph_agent_builder.schema.scrub import register_secret

            register_secret(secret_value)
            return SecretRef(secret_value)
        return {
            k: _resolve_refs(
                v, variables, diagnostics, node_id, field, vectorstore_names, field_def
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _resolve_refs(v, variables, diagnostics, node_id, field, vectorstore_names, field_def)
            for v in value
        ]
    return value


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def snapshot_digest(
    spec: FlowSpec,
    variables: VariablesProvider,
    tweaks: dict[str, dict[str, Any]] | None = None,
    vectorstore_names: set[str] | None = None,
) -> str:
    """Digest of everything P2 injects beyond the FlowSpec bytes: resolved
    values of referenced $var/$secret refs, $vectorstore existence, and tweaks.

    Folded into the compile-cache key so a rotated secret, an edited global
    variable, or per-run tweaks/header vars (§9.4) can never be served from a
    stale cached compile."""
    h = hashlib.sha256()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if "$vectorstore" in value:
                name = str(value["$vectorstore"])
                known = "?" if vectorstore_names is None else str(name in vectorstore_names)
                h.update(f"vs:{name}={known};".encode())
                return
            if set(value.keys()) == {"$var"}:
                name = str(value["$var"])
                resolved = (
                    variables.get_var(name)
                    if variables.has_var(name)
                    else _env_fallback(variables, name)
                )
                h.update(f"var:{name}={resolved!r};".encode())
                return
            if set(value.keys()) == {"$secret"}:
                name = str(value["$secret"])
                resolved = variables.get_secret(name) if variables.has_secret(name) else None
                h.update(f"secret:{name}={resolved!r};".encode())
                return
            for key in sorted(value):
                visit(value[key])
            return
        if isinstance(value, list):
            for item in value:
                visit(item)

    for node in spec.nodes:
        visit(node.config)
    if tweaks:
        h.update(json.dumps(tweaks, sort_keys=True, default=str).encode())
        for override in tweaks.values():
            visit(override)
    return h.hexdigest()[:16]


def resolve(
    spec: FlowSpec,
    registry: ComponentRegistry,
    variables: VariablesProvider,
    tweaks: dict[str, dict[str, Any]] | None = None,
    vectorstore_names: set[str] | None = None,
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
                    fix_hint="Install the providing package or check LAB_COMPONENTS_PATH.",
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

        # $var/$secret/$vectorstore refs → concrete values (E012/E013 when
        # missing); _resolve_refs enforces the E014 credential-leak guard at
        # any nesting depth, keyed off the owning field's class.
        field_map = cls.field_map()
        for fname in list(config.keys()):
            config[fname] = _resolve_refs(
                config[fname],
                variables,
                diagnostics,
                node.id,
                fname,
                vectorstore_names,
                field_map.get(fname),
            )

        # field-level validation (E010/E011, W301)
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
            from langgraph_agent_builder.sdk.ports import VectorStoreHandle

            schema = f.json_schema()
            if schema and not isinstance(value, (SecretRef, VectorStoreHandle)):
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
        # unknown keys are tolerated (forward compat) but flagged — catches
        # typo'd field names in hand-edited FlowSpecs that would vanish silently
        implicit_names = {f.name for f in cls._implicit_field_objects()}
        for fname in config:
            if fname not in field_map and fname not in implicit_names:
                diagnostics.append(
                    Diagnostic.make(
                        DiagnosticCode.W303,
                        f"unknown config key {fname!r} — not a field of "
                        f"{cls.component_id}; ignored",
                        node_id=node.id,
                        field=fname,
                        fix_hint="Check the field name against the component form.",
                    )
                )

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
