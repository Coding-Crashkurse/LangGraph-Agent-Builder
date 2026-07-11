"""Ports & the type system (SPEC §4.3).

Ports are Pydantic schemas; edge validation is structural, not bucket-based.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable
from enum import StrEnum
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage


class PortFamily(StrEnum):
    MESSAGE = "MESSAGE"
    DATA = "DATA"
    TABLE = "TABLE"
    DOCUMENTS = "DOCUMENTS"
    EMBEDDING = "EMBEDDING"
    MODEL = "MODEL"
    VECTORSTORE = "VECTORSTORE"
    TOOLSET = "TOOLSET"
    ROUTE = "ROUTE"
    FILE = "FILE"
    ANY = "ANY"


class PortSpec(BaseModel):
    schema_ref: str  # e.g. "lab:Message", "myco:TicketBatch"
    json_schema: dict[str, Any] = Field(default_factory=dict)
    family: PortFamily
    is_list: bool = False
    display_name: str | None = None

    model_config = ConfigDict(frozen=True)

    @cached_property
    def fingerprint(self) -> str:
        """Hashable identity for compatibility caching — the frozen model itself
        is unhashable because ``json_schema`` is a dict. display_name is
        deliberately excluded (it never affects compatibility)."""
        schema = json.dumps(self.json_schema, sort_keys=True, default=str)
        return f"{self.schema_ref}|{self.family.value}|{int(self.is_list)}|{schema}"


# --------------------------------------------------------------------------- payloads
class FileRef(BaseModel):
    file_id: str
    mime: str = "application/octet-stream"
    name: str = ""
    uri: str | None = None


class Message(BaseModel):
    """Chat message; converts losslessly to/from LangChain BaseMessage."""

    role: Literal["user", "assistant", "system", "tool"] = "user"
    content: str = ""
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    files: list[FileRef] = Field(default_factory=list)

    def to_langchain(self) -> BaseMessage:
        from langchain_core.messages import (
            AIMessage,
            HumanMessage,
            SystemMessage,
            ToolMessage,
        )

        kwargs: dict[str, Any] = {"content": self.content}
        if self.name:
            kwargs["name"] = self.name
        if self.metadata:
            kwargs["additional_kwargs"] = {"lga_metadata": self.metadata}
        match self.role:
            case "assistant":
                return AIMessage(**kwargs)
            case "system":
                return SystemMessage(**kwargs)
            case "tool":
                return ToolMessage(tool_call_id=self.metadata.get("tool_call_id", ""), **kwargs)
            case _:
                return HumanMessage(**kwargs)

    @classmethod
    def from_langchain(cls, msg: Any) -> Message:
        from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

        if isinstance(msg, cls):
            return msg
        role: Literal["user", "assistant", "system", "tool"] = "user"
        if isinstance(msg, AIMessage):
            role = "assistant"
        elif isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, ToolMessage):
            role = "tool"
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        metadata = dict(getattr(msg, "additional_kwargs", {}).get("lga_metadata", {}))
        return cls(role=role, content=content, name=getattr(msg, "name", None), metadata=metadata)


class Document(BaseModel):
    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None


class VectorStoreHandle(BaseModel):
    """Runtime handle for an injected vector store (SPEC §8b).

    Carries the *name* of a server-managed connection plus an optional default
    collection — never credentials, so it stays serializable and portable.
    The concrete provider is resolved lazily via ``ctx.vectorstores.get(name)``.
    """

    connection: str
    collection: str | None = None


class ToolDef(BaseModel):
    """Entry of a Toolset: name/description/args schema + a callable reference.

    ``callable_ref`` is runtime-only (not serialized into checkpoints as callables
    are resolved at compile time); it holds an async callable or LangChain tool.
    """

    name: str
    description: str = ""
    args_schema: dict[str, Any] = Field(default_factory=dict)
    callable_ref: Any = Field(default=None, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class LazyToolset:
    """Deferred toolset (e.g. MCP listing needs IO) — resolved at first run."""

    def __init__(self, factory: Callable[[], Awaitable[Iterable[ToolDef]]]) -> None:
        self._factory = factory
        self._cache: list[ToolDef] | None = None

    async def resolve(self) -> list[ToolDef]:
        if self._cache is None:
            self._cache = list(await self._factory())
        return self._cache

    def invalidate(self) -> None:
        self._cache = None


async def resolve_toolsets(tools: list[ToolDef | LazyToolset]) -> list[ToolDef]:
    """Flatten a mixed ToolDef/LazyToolset list into concrete ToolDefs."""
    out: list[ToolDef] = []
    for item in tools or []:
        if isinstance(item, LazyToolset):
            out.extend(await item.resolve())
        else:
            out.append(item)
    return out


# --------------------------------------------------------------------------- core specs
def _schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()


MESSAGE = PortSpec(
    schema_ref="lab:Message", json_schema=_schema(Message), family=PortFamily.MESSAGE
)
MESSAGES = PortSpec(
    schema_ref="lab:Messages",
    json_schema={"type": "array", "items": _schema(Message)},
    family=PortFamily.MESSAGE,
    is_list=True,
)
TEXT = PortSpec(schema_ref="lab:Text", json_schema={"type": "string"}, family=PortFamily.DATA)
JSON = PortSpec(schema_ref="lab:Json", json_schema={"type": "object"}, family=PortFamily.DATA)
TABLE = PortSpec(
    schema_ref="lab:Table",
    json_schema={"type": "array", "items": {"type": "object"}},
    family=PortFamily.TABLE,
    is_list=True,
)
DOCUMENTS = PortSpec(
    schema_ref="lab:Documents",
    json_schema={"type": "array", "items": _schema(Document)},
    family=PortFamily.DOCUMENTS,
    is_list=True,
)
EMBEDDING = PortSpec(schema_ref="lab:Embedding", json_schema={}, family=PortFamily.EMBEDDING)
LANGUAGE_MODEL = PortSpec(schema_ref="lab:LanguageModel", json_schema={}, family=PortFamily.MODEL)
VECTOR_STORE = PortSpec(
    schema_ref="lab:VectorStore",
    json_schema=_schema(VectorStoreHandle),
    family=PortFamily.VECTORSTORE,
)
TOOLSET = PortSpec(
    schema_ref="lab:Toolset",
    json_schema={"type": "array", "items": _schema(ToolDef)},
    family=PortFamily.TOOLSET,
    is_list=True,
)
TOOLSET_LIST = TOOLSET
ROUTE = PortSpec(schema_ref="lab:Route", json_schema={"type": "string"}, family=PortFamily.ROUTE)
FILE_REF = PortSpec(schema_ref="lab:FileRef", json_schema=_schema(FileRef), family=PortFamily.FILE)
ANY = PortSpec(schema_ref="lab:Any", json_schema={}, family=PortFamily.ANY)

CORE_PORTS: dict[str, PortSpec] = {
    p.schema_ref: p
    for p in [
        MESSAGE,
        MESSAGES,
        TEXT,
        JSON,
        TABLE,
        DOCUMENTS,
        EMBEDDING,
        LANGUAGE_MODEL,
        VECTOR_STORE,
        TOOLSET,
        ROUTE,
        FILE_REF,
        ANY,
    ]
}


def json_port(schema: dict[str, Any] | None = None, ref: str = "lab:Json") -> PortSpec:
    """A Json port carrying a declared payload schema → structural edge checks."""
    return PortSpec(
        schema_ref=ref, json_schema=schema or {"type": "object"}, family=PortFamily.DATA
    )


# --------------------------------------------------------------------------- compatibility
class Compat(BaseModel):
    compatible: bool
    warning: str | None = None  # W2xx code when compatible-with-caveat
    coercion: str | None = None  # registered coercion name applied on the edge
    reason: str = ""


def _structural_subset(source: dict[str, Any], target: dict[str, Any]) -> bool:
    """Does `target` accept every payload `source` can produce?

    Practical structural check: empty target schema accepts all; same type and,
    for objects, target's required properties must exist in source with
    compatible types; for arrays, recurse on items.
    """
    if not target:
        return True
    if not source:
        return False
    s_type, t_type = source.get("type"), target.get("type")
    if t_type is None:
        return True
    if s_type != t_type:
        return False
    if t_type == "object":
        s_props = source.get("properties", {})
        t_props = target.get("properties", {})
        for req in target.get("required", []):
            if req not in s_props:
                return False
            if not _structural_subset(s_props[req], t_props.get(req, {})):
                return False
        return True
    if t_type == "array":
        return _structural_subset(source.get("items", {}), target.get("items", {}))
    return True


def _check(source: PortSpec, target: PortSpec) -> Compat:
    from langgraph_agent_builder.sdk.ports import coerce

    # 1. ANY matches everything, with W201
    if source.family == PortFamily.ANY or target.family == PortFamily.ANY:
        return Compat(compatible=True, warning="W201", reason="ANY-typed edge")

    # registered coercions win outright — their functions own the shape change
    # (e.g. documents_to_text is list → scalar by design)
    early = coerce.find(source, target)
    if early is not None:
        return Compat(compatible=True, warning="W203", coercion=early, reason=f"coercion {early}")

    list_mismatch = source.is_list != target.is_list
    wrappable = not source.is_list and target.is_list

    def wrapped(inner: Compat) -> Compat:
        if not list_mismatch:
            return inner
        return Compat(
            compatible=True,
            warning="W202",
            coercion=(inner.coercion + "+wrap_list") if inner.coercion else "wrap_list",
            reason="auto list-wrap",
        )

    if list_mismatch and not wrappable:
        return Compat(
            compatible=False,
            reason=f"list → scalar is never implicit ({source.schema_ref} → {target.schema_ref})",
        )

    # scalar→list compares against the target's item schema
    target_schema = target.json_schema
    if list_mismatch and isinstance(target_schema, dict) and "items" in target_schema:
        target_schema = target_schema["items"]

    # 2. same schema_ref
    if source.schema_ref == target.schema_ref and not list_mismatch:
        return Compat(compatible=True, reason="same schema_ref")

    # 3. same family → structural subset check
    if source.family == target.family:
        if _structural_subset(source.json_schema, target_schema):
            return wrapped(Compat(compatible=True, reason="structural subset"))
        return Compat(
            compatible=False,
            reason=f"{source.schema_ref} does not structurally satisfy {target.schema_ref}",
        )

    # 4. cross-family → registered coercions only
    name = coerce.find(source, target)
    if name is not None:
        return wrapped(
            Compat(compatible=True, warning="W203", coercion=name, reason=f"coercion {name}")
        )
    return Compat(
        compatible=False,
        reason=f"incompatible families {source.family} → {target.family} "
        f"({source.schema_ref} → {target.schema_ref})",
    )


_compat_cache: dict[tuple[str, str], Compat] = {}
_COMPAT_CACHE_MAX = 4096


def check_compatibility(source: PortSpec, target: PortSpec) -> Compat:
    """Edge validation algorithm (SPEC §4.3), coercions included. Results are
    cached per (source, target) ``PortSpec.fingerprint`` pair."""
    key = (source.fingerprint, target.fingerprint)
    hit = _compat_cache.get(key)
    if hit is not None:
        return hit
    result = _check(source, target)
    if len(_compat_cache) >= _COMPAT_CACHE_MAX:
        _compat_cache.clear()
    _compat_cache[key] = result
    return result
