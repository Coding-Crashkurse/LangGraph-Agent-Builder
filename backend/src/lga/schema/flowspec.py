"""FlowSpec — the versioned flow document (SPEC §5.2). Source of truth."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from lga.errors import LgaValueError

SCHEMA_VERSION = "2"
RESERVED_NODE_IDS = {"start", "end"}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class A2ASettings(BaseModel):
    enabled: bool = False
    agent_name: str = ""  # falls back to flow.name
    description: str = ""  # REQUIRED before publish with enabled (E060)
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    input_modes: list[str] = Field(default_factory=lambda: ["text/plain", "application/json"])
    output_modes: list[str] = Field(default_factory=lambda: ["text/plain", "application/json"])
    auth: Literal["public", "api-key"] = "public"
    stream_tokens: bool = True
    push_notifications: bool = True


class McpSettings(BaseModel):
    enabled: bool = False
    tool_name: str = ""  # default: flow slug — never a UUID
    description: str = ""  # REQUIRED before publish with enabled (E062)
    auto_resolve_interrupts: Literal["approve", "reject"] | None = None
    timeout_s: float | None = None


class FlowRunSettings(BaseModel):
    recursion_limit: int = 50


class FlowMeta(BaseModel):
    name: str
    slug: str
    description: str = ""
    icon: str = "bot"
    tags: list[str] = Field(default_factory=list)
    locked: bool = False  # SPEC §9.1 — PATCH rejected while locked
    a2a: A2ASettings = Field(default_factory=A2ASettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    settings: FlowRunSettings = Field(default_factory=FlowRunSettings)

    @field_validator("slug")
    @classmethod
    def _slug_ok(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("slug must be url-safe kebab-case ([a-z0-9-])")
        return v

    @model_validator(mode="after")
    def _exclusive_serving(self) -> FlowMeta:
        """Serving surfaces are mutually exclusive (SPEC §7.1/§8.1): a published
        flow is an A2A agent XOR an MCP tool XOR a plain REST API — never two at
        once. A2A takes precedence if a spec somehow enables both."""
        if self.a2a.enabled and self.mcp.enabled:
            self.mcp.enabled = False
        return self

    @property
    def serve_mode(self) -> Literal["a2a", "mcp", "api"]:
        """The single active serving surface (A2A default for new flows)."""
        if self.a2a.enabled:
            return "a2a"
        if self.mcp.enabled:
            return "mcp"
        return "api"


class Position(BaseModel):
    x: float = 0
    y: float = 0


class NodeSpec(BaseModel):
    id: str
    component_id: str
    component_version: str = "1.0.0"
    label: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    position: Position = Field(default_factory=Position)
    notes: str = ""

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_\-]*$", v):
            raise ValueError("node id must be an identifier-like string")
        return v


class EdgeEndpointSource(BaseModel):
    node: str
    output: str


class EdgeEndpointTarget(BaseModel):
    node: str
    input: str


class EdgeSpec(BaseModel):
    id: str
    kind: Literal["data", "tool", "router"] = "data"
    source: EdgeEndpointSource
    target: EdgeEndpointTarget


class StickyNote(BaseModel):
    id: str
    text: str = ""
    position: Position = Field(default_factory=Position)
    color: str = "amber"


class FlowUI(BaseModel):
    viewport: dict[str, Any] = Field(default_factory=dict)
    sticky_notes: list[StickyNote] = Field(default_factory=list)


class FlowSpec(BaseModel):
    schema_version: str = SCHEMA_VERSION
    flow: FlowMeta
    nodes: list[NodeSpec] = Field(default_factory=list)
    edges: list[EdgeSpec] = Field(default_factory=list)
    ui: FlowUI = Field(default_factory=FlowUI)
    meta: dict[str, Any] = Field(default_factory=dict)

    def node(self, node_id: str) -> NodeSpec | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def canonical_json(self) -> str:
        """Deterministic serialization — cache key input (SPEC §5.3)."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class FlowSpecError(LgaValueError):
    """Raised by parse_flowspec on schema violations (→ E001)."""


def _migrate_1_to_2(raw: dict[str, Any]) -> dict[str, Any]:
    """v1 → v2 (lossless): adds ``flow.locked`` and the ``flow.mcp`` block."""
    raw = dict(raw)
    flow = dict(raw.get("flow") or {})
    flow.setdefault("locked", False)
    flow.setdefault("mcp", {"enabled": False})
    raw["flow"] = flow
    raw["schema_version"] = "2"
    return raw


def migrate_schema(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate older schema_versions to the current one."""
    version = str(raw.get("schema_version", "") or "1")
    if version == SCHEMA_VERSION:
        return raw
    if version == "1":
        return _migrate_1_to_2(raw)
    raise FlowSpecError(f"unknown schema_version {version!r} (supported: {SCHEMA_VERSION})")


def parse_flowspec(source: FlowSpec | dict[str, Any] | str | Path) -> FlowSpec:
    if isinstance(source, FlowSpec):
        return source
    if isinstance(source, Path):
        source = json.loads(source.read_text(encoding="utf-8"))
    elif isinstance(source, str):
        p = Path(source)
        if p.suffix == ".json" and p.exists():
            source = json.loads(p.read_text(encoding="utf-8"))
        else:
            source = json.loads(source)
    assert isinstance(source, dict)
    try:
        return FlowSpec.model_validate(migrate_schema(source))
    except FlowSpecError:
        raise
    except Exception as exc:
        raise FlowSpecError(str(exc)) from exc


def export_json_schema() -> dict[str, Any]:
    return FlowSpec.model_json_schema()
