"""Structured Output — force Json per schema from a model (SPEC §12.2).

The schema is edited as a TableInput of ``name`` / ``description`` / ``type``
rows (Langflow parity); a raw JSON-schema dict from pre-1.1.0 nodes is migrated
to rows and still accepted at runtime.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from langchain_core.messages import HumanMessage, SystemMessage

from lga.sdk import Component, Output, fields, ports
from lga.sdk.component import BuildContext, NodeConfig, NodeFn
from lga.sdk.runtime import get_run_context

_JSON_TYPES = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}
_ROW_TYPES = {v: k for k, v in _JSON_TYPES.items()}


def _rows_to_schema(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Schema-editor rows → JSON schema the model is prompted with."""
    props: dict[str, Any] = {}
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        prop: dict[str, Any] = {"type": _JSON_TYPES.get(str(row.get("type") or "str"), "string")}
        if row.get("description"):
            prop["description"] = str(row["description"])
        props[name] = prop
    if not props:
        return {"type": "object"}
    return {"type": "object", "properties": props, "required": list(props)}


def _schema_to_rows(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Legacy JSON-schema dict → schema-editor rows (config migration)."""
    rows: list[dict[str, Any]] = []
    for name, prop in (schema.get("properties") or {}).items():
        prop = prop if isinstance(prop, dict) else {}
        rows.append(
            {
                "name": name,
                "description": str(prop.get("description") or ""),
                "type": _ROW_TYPES.get(str(prop.get("type")), "str"),
            }
        )
    return rows


class StructuredOutput(Component):
    component_id = "lga.llm.structured_output"
    display_name = "Structured Output"
    description = "Force a model to emit JSON matching a schema."
    icon = "braces"
    category = "llm"
    version: ClassVar[str] = "1.1.0"  # 1.0.0 → output_schema was a raw JSON-schema dict

    inputs = [
        fields.ModelInput(
            name="model", display_name="Model", required=True, as_port=ports.LANGUAGE_MODEL
        ),
        fields.TableInput(
            name="output_schema",
            display_name="Output Schema",
            info="One row per output field.",
            columns=[
                fields.ColumnSpec(name="name", type="str"),
                fields.ColumnSpec(name="description", type="str"),
                fields.ColumnSpec(name="type", type="str"),
            ],
            required=True,
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.MESSAGE),
        fields.MultilineInput(name="instructions", display_name="Instructions", advanced=True),
    ]
    outputs = [
        Output(name="json", display_name="Json", port=ports.JSON),
        Output(name="table", display_name="Table", port=ports.TABLE),
    ]

    @classmethod
    def migrate_config(cls, old_version: str, config: NodeConfig) -> NodeConfig:
        cfg = dict(config)
        schema = cfg.get("output_schema")
        if isinstance(schema, dict):
            cfg["output_schema"] = _schema_to_rows(schema)
        return cfg

    def build(self, ctx: BuildContext) -> NodeFn:
        from lga.components.llm._models import parse_json_reply, resolve_model, stream_completion
        from lga.sdk.templating import message_text

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            raw_schema = ctx.get_field("output_schema")
            if isinstance(raw_schema, dict):  # pre-1.1.0 JSON-schema value
                schema = raw_schema or {"type": "object"}
            else:
                schema = _rows_to_schema(list(raw_schema or []))
            model = resolve_model(ctx.get_input(state, "model"))
            inbound = ctx.get_input(state, "input")
            text = message_text(inbound) if inbound is not None else ""
            raw = await stream_completion(
                model,
                [
                    SystemMessage(
                        content=(ctx.get_field("instructions") or "Extract structured data.")
                        + "\nRespond ONLY with JSON matching this schema:\n"
                        + json.dumps(schema)
                    ),
                    HumanMessage(content=text),
                ],
                get_run_context(config),
                stream=False,
            )
            value = parse_json_reply(raw)
            table = value if isinstance(value, list) else value.get("rows", [value])
            return {"json": value, "table": table if isinstance(table, list) else [table]}

        return node
