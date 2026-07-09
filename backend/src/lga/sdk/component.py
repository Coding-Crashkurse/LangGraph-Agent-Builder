"""Component base class (SPEC §4.1) + BuildContext.

A component author writes one class; from it we derive the node UI form, the
input/output ports, edge validation rules, the LangGraph node function, the
optional agent-tool schema, and docs.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import StrEnum
from typing import Any, ClassVar

from lga.sdk.fields import Field, MultiselectInput, PromptInput
from lga.sdk.outputs import Output
from lga.sdk.ports import ROUTE, TEXT, PortSpec, ToolDef
from lga.sdk.ports import coerce as _coerce

NodeConfig = dict[str, Any]
NodeFn = Callable[..., Awaitable[dict[str, Any]]]

PROMPT_VAR_RE = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")


def slugify(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return out or "node"


class NodeKind(StrEnum):
    TASK = "task"
    ROUTER = "router"
    INTERRUPT = "interrupt"
    TERMINAL = "terminal"


class SecretRef(str):
    """Marker type: a resolved secret value. Repr never leaks the value."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "SecretRef('***')"


class SecretsResolver:
    """Resolves ``{"$secret": name}`` refs from a pre-fetched mapping."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    def resolve(self, name: str) -> SecretRef:
        if name not in self._values:
            raise KeyError(f"secret {name!r} not available")
        return SecretRef(self._values[name])

    def has(self, name: str) -> bool:
        return name in self._values


@dataclass
class InputBinding:
    """How one input port of a node gets its runtime value."""

    input_name: str
    channel: str | None = None  # "ports" key "{src}.{out}"; None → constant
    coercion: str | None = None
    constant: Any = None  # test-harness / unconnected fallback

    def read(self, state: dict[str, Any]) -> Any:
        if self.channel is None:
            value = self.constant
        else:
            value = state.get("ports", {}).get(self.channel)
        if self.coercion and value is not None:
            value = _coerce.apply(self.coercion, value)
        return value


@dataclass
class BuildContext:
    """Available at build/compile time (SPEC §4.1)."""

    node_id: str
    flow_id: str = ""
    label: str = ""
    config: NodeConfig = dc_field(default_factory=dict)
    secrets: SecretsResolver = dc_field(default_factory=SecretsResolver)
    registry: Any = None
    logger: logging.Logger = dc_field(default_factory=lambda: logging.getLogger("lga.component"))
    input_bindings: dict[str, InputBinding] = dc_field(default_factory=dict)
    tools: list[ToolDef] = dc_field(default_factory=list)
    settings: Any = None  # lga Settings when compiled server-side; None headless

    def get_field(self, name: str) -> Any:
        """Resolved config value (tweaks + $var/$secret refs already applied in P2)."""
        return self.config.get(name)

    def has_input(self, name: str) -> bool:
        return name in self.input_bindings

    def get_input(self, state: dict[str, Any], name: str) -> Any:
        """Runtime value of an input port; falls back to the widget value."""
        binding = self.input_bindings.get(name)
        if binding is not None:
            value = binding.read(state)
            if value is not None:
                return value
        return self.config.get(name)


class Component(ABC):
    """Base class for all components (SPEC §4.1)."""

    # ---- identity (stability rules §4.9) ----
    component_id: ClassVar[str]  # REQUIRED, immutable, e.g. "lga.llm.llm_call"
    version: ClassVar[str] = "1.0.0"
    display_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    icon: ClassVar[str] = "box"
    category: ClassVar[str] = "data"
    tags: ClassVar[list[str]] = []
    documentation_url: ClassVar[str | None] = None
    priority: ClassVar[int | None] = None  # palette sort within category (§18.2)
    beta: ClassVar[bool] = False
    legacy: ClassVar[bool] = False
    successor: ClassVar[str | None] = None  # replacement component_id for legacy (§4.11)

    # ---- interface ----
    inputs: ClassVar[list[Field]] = []
    outputs: ClassVar[list[Output]] = []
    dynamic_outputs_from: ClassVar[str | None] = None  # field name providing router labels

    # ---- behavior flags ----
    node_kind: ClassVar[NodeKind] = NodeKind.TASK
    tool_mode_supported: ClassVar[bool] = False
    # Langflow parity: the toolset port only shows when Tool Mode is on.
    # Pure tool components (calculator, http_request, …) default it to True.
    tool_mode_default: ClassVar[bool] = False

    # ------------------------------------------------------------------ lifecycle
    @abstractmethod
    def build(self, ctx: BuildContext) -> NodeFn:
        """Return an async LangGraph node fn: (state, config) -> partial state update."""

    def on_field_change(self, config: NodeConfig, field_name: str, value: Any) -> NodeConfig:
        config = dict(config)
        config[field_name] = value
        return config

    async def health_check(self, ctx: BuildContext) -> None:  # noqa: B027
        """Deep-validate hook (E9xx family); default: nothing to check."""

    @classmethod
    def migrate_config(cls, old_version: str, config: NodeConfig) -> NodeConfig:
        return config

    # ------------------------------------------------------------------ derived interface
    @classmethod
    def field_map(cls) -> dict[str, Field]:
        return {f.name: f for f in cls.inputs}

    @classmethod
    def tool_mode_enabled(cls, config: NodeConfig) -> bool:
        return bool(config.get("tool_mode", cls.tool_mode_default))

    @classmethod
    def outputs_for_config(cls, config: NodeConfig) -> list[Output]:
        """Effective outputs; routers with dynamic labels regenerate here.

        tool_mode_supported components gain a `toolset` output while Tool Mode
        is enabled (config `tool_mode`, default `tool_mode_default`) so they
        can be attached to agents via tool edges (SPEC §4.7, §18 parity).
        """
        if cls.dynamic_outputs_from:
            labels = config.get(cls.dynamic_outputs_from) or []
            if not labels:
                f = cls.field_map().get(cls.dynamic_outputs_from)
                if isinstance(f, MultiselectInput):
                    labels = f.default or []
            outs = [Output(name=str(lb), port=ROUTE) for lb in labels]
        else:
            outs = list(cls.outputs)
        if (
            cls.tool_mode_supported
            and cls.tool_mode_enabled(config)
            and not any(o.name == "toolset" for o in outs)
        ):
            from lga.sdk.ports import TOOLSET

            outs = [*outs, Output(name="toolset", display_name="Toolset", port=TOOLSET)]
        return outs

    @classmethod
    def input_ports_for_config(cls, config: NodeConfig) -> dict[str, PortSpec]:
        """Input ports: handle-capable fields + dynamic PromptInput {var} ports."""
        ports: dict[str, PortSpec] = {}
        for f in cls.inputs:
            if f.as_port is not None:
                ports[f.name] = f.as_port
            if isinstance(f, PromptInput):
                template = config.get(f.name) or f.default or ""
                for var in PROMPT_VAR_RE.findall(str(template)):
                    ports.setdefault(var, TEXT)
        return ports

    @classmethod
    def config_schema(cls) -> dict[str, Any]:
        """JSON Schema for node config values (client-side validation)."""
        props: dict[str, Any] = {}
        required: list[str] = []
        ref_wrapper = {
            "type": "object",
            "properties": {
                "$var": {"type": "string"},
                "$secret": {"type": "string"},
            },
        }
        for f in cls.inputs:
            if f.port_only:
                continue
            base = f.json_schema() or {}
            if f.accepts_global_variable and base.get("type") == "string":
                props[f.name] = {"anyOf": [base, ref_wrapper]}
            else:
                props[f.name] = base
            if f.required and f.default is None:
                required.append(f.name)
        schema: dict[str, Any] = {
            "type": "object",
            "properties": props,
            "additionalProperties": False,
        }
        if required:
            schema["required"] = required
        return schema

    @classmethod
    def descriptor(cls, config: NodeConfig | None = None) -> dict[str, Any]:
        """The JSON descriptor served by GET /api/v1/components (SPEC §4.2)."""
        config = config or {}
        return {
            "component_id": cls.component_id,
            "version": cls.version,
            "display_name": cls.display_name or cls.__name__,
            "description": cls.description,
            "icon": cls.icon,
            "category": cls.category,
            "tags": list(cls.tags),
            "documentation_url": cls.documentation_url,
            "priority": cls.priority,
            "beta": cls.beta,
            "legacy": cls.legacy,
            "successor": cls.successor,
            "node_kind": cls.node_kind.value,
            "tool_mode_supported": cls.tool_mode_supported,
            "tool_mode_default": cls.tool_mode_default,
            "dynamic_outputs_from": cls.dynamic_outputs_from,
            "fields": [f.descriptor() for f in cls.inputs] + cls._implicit_fields(),
            "outputs": [o.descriptor() for o in cls.outputs_for_config(config)],
            "input_ports": {
                name: spec.model_dump(mode="json")
                for name, spec in cls.input_ports_for_config(config).items()
            },
            "config_schema": cls.config_schema(),
        }

    @classmethod
    def _implicit_fields(cls) -> list[dict[str, Any]]:
        """Synthetic form fields every tool-capable component gets (§4.7):
        the Tool Mode toggle plus editable tool name/description — Langflow
        lesson: names/descriptions drive agent tool selection."""
        if not cls.tool_mode_supported:
            return []
        from lga.sdk.fields import BoolInput, MultilineInput, StrInput

        return [
            BoolInput(
                name="tool_mode",
                display_name="Tool Mode",
                info="Expose this node as a tool (adds the Toolset port on top).",
                default=cls.tool_mode_default,
            ).descriptor(),
            StrInput(
                name="tool_name",
                display_name="Tool Name",
                info="Agents pick tools by name — keep it verb-like.",
                advanced=True,
            ).descriptor(),
            MultilineInput(
                name="tool_description",
                display_name="Tool Description",
                info="Shown to the agent; decisive for tool selection.",
                advanced=True,
            ).descriptor(),
        ]

    # ------------------------------------------------------------------ tool mode (§4.7)
    @classmethod
    def tool_schema(cls, config: NodeConfig, label: str) -> dict[str, Any]:
        props: dict[str, Any] = {}
        required: list[str] = []
        for f in cls.inputs:
            if f.tool_mode:
                props[f.name] = f.json_schema() or {"type": "string"}
                if f.required:
                    required.append(f.name)
        schema: dict[str, Any] = {"type": "object", "properties": props}
        if required:
            schema["required"] = required
        return {
            "name": config.get("tool_name") or slugify(label or cls.display_name),
            "description": config.get("tool_description") or cls.description,
            "args_schema": schema,
        }
