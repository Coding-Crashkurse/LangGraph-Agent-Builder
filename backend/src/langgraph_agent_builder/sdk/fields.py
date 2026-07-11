"""Field classes — the UI input catalog (SPEC §4.2).

Every field is a Pydantic model; the class name is the wire ``type`` in the
component descriptor and keys the frontend ``FieldWidgetRegistry``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_validator
from pydantic import Field as PydField

from langgraph_agent_builder.sdk.ports import PortSpec


class Option(BaseModel):
    value: str
    label: str
    description: str | None = None
    icon: str | None = None


class ColumnSpec(BaseModel):
    name: str
    display_name: str = ""
    type: Literal["str", "int", "float", "bool"] = "str"

    @model_validator(mode="after")
    def _default_display(self) -> ColumnSpec:
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()
        return self


class Field(BaseModel):
    """Base for all input fields (SPEC §4.2 common attributes)."""

    name: str
    display_name: str = ""
    info: str = ""
    required: bool = False
    default: Any = None
    advanced: bool = False
    show: bool = True
    dynamic: bool = False
    real_time_refresh: bool = False
    refresh_button: bool = False
    placeholder: str = ""
    tool_mode: bool = False
    accepts_global_variable: bool = True
    deprecated: bool = False
    # handle capability
    as_port: PortSpec | None = None
    port_only: bool = False

    @model_validator(mode="after")
    def _default_display_name(self) -> Field:
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()
        return self

    # ------------------------------------------------------------------ wire
    @property
    def field_type(self) -> str:
        return type(self).__name__

    def descriptor(self) -> dict[str, Any]:
        d = self.model_dump(mode="json")
        d["type"] = self.field_type
        return d

    def json_schema(self) -> dict[str, Any]:
        """JSON Schema fragment for this field's *value* (drives client validation)."""
        return {}


class StrInput(Field):
    max_length: int | None = None

    def json_schema(self) -> dict[str, Any]:
        s: dict[str, Any] = {"type": "string"}
        if self.max_length:
            s["maxLength"] = self.max_length
        return s


class MultilineInput(StrInput):
    pass


class IntInput(Field):
    min: int | None = None
    max: int | None = None
    step: int = 1

    def json_schema(self) -> dict[str, Any]:
        s: dict[str, Any] = {"type": "integer"}
        if self.min is not None:
            s["minimum"] = self.min
        if self.max is not None:
            s["maximum"] = self.max
        return s


class FloatInput(Field):
    min: float | None = None
    max: float | None = None
    step: float = 0.1

    def json_schema(self) -> dict[str, Any]:
        s: dict[str, Any] = {"type": "number"}
        if self.min is not None:
            s["minimum"] = self.min
        if self.max is not None:
            s["maximum"] = self.max
        return s


class BoolInput(Field):
    def json_schema(self) -> dict[str, Any]:
        return {"type": "boolean"}


class SliderInput(Field):
    min: float
    max: float
    step: float
    min_label: str = ""  # e.g. "Precise" endpoint label (SPEC §4.2)
    max_label: str = ""  # e.g. "Creative"

    def json_schema(self) -> dict[str, Any]:
        return {"type": "number", "minimum": self.min, "maximum": self.max}


class DropdownInput(Field):
    options: list[str] | list[Option] = PydField(default_factory=list)
    combobox: bool = False
    options_source: str | None = None  # server callback via on_field_change

    def option_values(self) -> list[str]:
        return [o.value if isinstance(o, Option) else o for o in self.options]

    def json_schema(self) -> dict[str, Any]:
        s: dict[str, Any] = {"type": "string"}
        values = self.option_values()
        if values and not self.combobox and not self.options_source:
            s["enum"] = values
        return s


class MultiselectInput(Field):
    options: list[str] | list[Option] = PydField(default_factory=list)
    options_source: str | None = None

    def option_values(self) -> list[str]:
        return [o.value if isinstance(o, Option) else o for o in self.options]

    def json_schema(self) -> dict[str, Any]:
        item: dict[str, Any] = {"type": "string"}
        values = self.option_values()
        if values and not self.options_source:
            item["enum"] = values
        return {"type": "array", "items": item}


class TabInput(Field):
    options: list[str] | list[Option] = PydField(default_factory=list)

    @model_validator(mode="after")
    def _max_five(self) -> TabInput:
        if len(self.options) > 5:
            raise ValueError("TabInput supports at most 5 options")
        return self

    def option_values(self) -> list[str]:
        return [o.value if isinstance(o, Option) else o for o in self.options]

    def json_schema(self) -> dict[str, Any]:
        return {"type": "string", "enum": self.option_values()}


class SecretInput(Field):
    """Value stored as a secret ref ({"$secret": name}); never echoed back."""

    def json_schema(self) -> dict[str, Any]:
        return {
            "anyOf": [
                {"type": "string"},
                {
                    "type": "object",
                    "properties": {"$secret": {"type": "string"}},
                    "required": ["$secret"],
                },
            ]
        }


class MultilineSecretInput(SecretInput):
    pass


class DictInput(Field):
    value_type: Literal["str", "int", "float", "bool", "any"] = "str"

    def json_schema(self) -> dict[str, Any]:
        return {"type": "object"}


class NestedDictInput(Field):
    schema_: dict[str, Any] | None = PydField(default=None, alias="schema")

    model_config = {"populate_by_name": True}

    def json_schema(self) -> dict[str, Any]:
        return self.schema_ or {"type": "object"}


class TableInput(Field):
    columns: list[ColumnSpec] = PydField(default_factory=list)

    def json_schema(self) -> dict[str, Any]:
        props = {
            c.name: {
                "type": {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}[
                    c.type
                ]
            }
            for c in self.columns
        }
        return {"type": "array", "items": {"type": "object", "properties": props}}


class FileInput(Field):
    file_types: list[str] = PydField(default_factory=list)
    multiple: bool = False

    def json_schema(self) -> dict[str, Any]:
        if self.multiple:
            return {"type": "array", "items": {"type": "string"}}
        return {"type": "string"}


class CodeInput(Field):
    language: str = "jinja2"

    def json_schema(self) -> dict[str, Any]:
        return {"type": "string"}


class PromptInput(Field):
    """Prompt editor. ``{variables}`` spawn dynamic input ports per variable."""

    def json_schema(self) -> dict[str, Any]:
        return {"type": "string"}


class ModelInput(Field):
    """Provider+model picker; resolves to a LanguageModel handle."""

    providers: list[str] | None = None

    def json_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "provider": {"type": "string"},
                "model": {"type": "string"},
                "temperature": {"type": "number"},
            },
            "required": ["provider", "model"],
        }


class EmbeddingModelInput(Field):
    """Provider+model picker resolving to an Embedding handle (SPEC §4.2, §8b)."""

    providers: list[str] | None = None

    def json_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "provider": {"type": "string"},
                "model": {"type": "string"},
            },
            "required": ["provider", "model"],
        }


class VectorStoreInput(Field):
    """Named Vector Store Connection + collection picker (SPEC §4.2, §8b).

    Value: ``{"$vectorstore": "<connection>", "collection": "<name>"}``. The
    collection dropdown is populated via ``options_source`` (list_collections).
    """

    allow_create_collection: bool = False
    options_source: str | None = None  # server callback populating the collection dropdown

    def json_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "$vectorstore": {"type": "string"},
                "connection": {"type": "string"},
                "collection": {"type": "string"},
            },
        }


class QueryInput(StrInput):
    tool_mode: bool = True


class LinkInput(Field):
    href_from: str = ""

    def json_schema(self) -> dict[str, Any]:
        return {"type": "string"}


class McpInput(Field):
    """MCP server picker + tool multiselect (backs MCP Toolset, SPEC §8.4)."""

    def json_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {"type": "string"},
                "tools": {"type": "array", "items": {"type": "string"}},
            },
        }


class ResourceRefInput(Field):
    """Picker for a named Resource (the Resources layer).

    Value: ``{"$resource": "<name>"}`` plus optional extra keys (e.g. ``model``
    for a ``model_provider``, ``collection`` for a ``knowledge_base``) carried
    through as the handle payload. ``resource_type`` pins which resource kind is
    accepted (E017 fires on a type mismatch at compile time); ``options_source``
    names the server callback populating the picker.
    """

    resource_type: Literal["model_provider", "knowledge_base", "mcp_server", "a2a_agent"]
    options_source: str | None = None  # server callback populating the resource dropdown

    def json_schema(self) -> dict[str, Any]:
        # extra keys (model/collection/…) are permitted alongside $resource
        return {
            "type": "object",
            "properties": {"$resource": {"type": "string"}},
            "required": ["$resource"],
        }


class HandleField(Field):
    """Pure connection input: no widget, handle only."""

    port_only: bool = True

    @model_validator(mode="after")
    def _needs_port(self) -> HandleField:
        if self.as_port is None:
            raise ValueError("HandleField requires as_port")
        return self


class ToolsInput(Field):
    """Tool port; accepts Toolset edges (dashed sky)."""

    port_only: bool = True

    @model_validator(mode="after")
    def _tool_port(self) -> ToolsInput:
        if self.as_port is None:
            from langgraph_agent_builder.sdk.ports import TOOLSET_LIST

            self.as_port = TOOLSET_LIST
        return self


_FIELD_CLASSES: list[type[Field]] = [
    StrInput,
    MultilineInput,
    IntInput,
    FloatInput,
    BoolInput,
    SliderInput,
    DropdownInput,
    MultiselectInput,
    TabInput,
    SecretInput,
    MultilineSecretInput,
    DictInput,
    NestedDictInput,
    TableInput,
    FileInput,
    CodeInput,
    PromptInput,
    ModelInput,
    EmbeddingModelInput,
    VectorStoreInput,
    ResourceRefInput,
    QueryInput,
    LinkInput,
    McpInput,
    HandleField,
    ToolsInput,
]

FIELD_TYPES: dict[str, type[Field]] = {cls.__name__: cls for cls in _FIELD_CLASSES}
