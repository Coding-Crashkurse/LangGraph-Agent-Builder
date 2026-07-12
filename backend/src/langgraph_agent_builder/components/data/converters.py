"""Data components (SPEC §12.6): Prompt Template, Type Convert, JSON Extract, Parser."""

from __future__ import annotations

import json
import re
from typing import Any

from langgraph_agent_builder.sdk import Component, Output, fields, ports
from langgraph_agent_builder.sdk.component import BuildContext, NodeConfig, NodeFn
from langgraph_agent_builder.sdk.ports import Document, Message
from langgraph_agent_builder.sdk.templating import message_text, render_prompt


class PromptTemplate(Component):
    component_id = "lab.data.prompt_template"
    display_name = "Prompt"
    description = (
        "Compose a prompt from a template — each {variable} becomes an input port "
        "(wire Documents, Text or values in; Documents coerce to text). Outputs the "
        "rendered Text/Message to feed an LLM Agent's input or an LLM Call {var}."
    )
    icon = "file-text"
    category = "io"
    priority = 30

    inputs = [
        fields.PromptInput(name="template", display_name="Template", required=True),
    ]
    outputs = [
        Output(name="text", display_name="Text", port=ports.TEXT),
        Output(name="message", display_name="Message", port=ports.MESSAGE),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        from langgraph_agent_builder.components.llm.llm_call import collect_prompt_values

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            template = str(ctx.get_field("template") or "")
            text = render_prompt(template, collect_prompt_values(ctx, state, template))
            return {"text": text, "message": Message(role="user", content=text)}

        return node


CONVERSIONS = {
    "message_to_text": (ports.MESSAGE, ports.TEXT),
    "text_to_message": (ports.TEXT, ports.MESSAGE),
    "documents_to_text": (ports.DOCUMENTS, ports.TEXT),
    "json_to_text": (ports.JSON, ports.TEXT),
    "text_to_json": (ports.TEXT, ports.JSON),
    "table_to_json": (ports.TABLE, ports.JSON),
    "json_to_table": (ports.JSON, ports.TABLE),
}


class TypeConvert(Component):
    component_id = "lab.data.type_convert"
    legacy = True
    display_name = "Type Convert"
    description = "Explicit conversions between port types, incl. Documents→Text template."
    icon = "repeat"
    category = "data"

    inputs = [
        fields.DropdownInput(
            name="conversion",
            display_name="Conversion",
            options=list(CONVERSIONS.keys()),  # a growing enum → dropdown, not 5-tab cap
            default="message_to_text",
            required=True,
            real_time_refresh=True,
        ),
        fields.MultilineInput(
            name="documents_template",
            display_name="Documents Template",
            info="jinja template per document; {{ page_content }} and {{ metadata }} available.",
            default="{{ page_content }}",
            advanced=True,
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.ANY),
    ]
    outputs = [Output(name="output", display_name="Output", port=ports.ANY)]

    @classmethod
    def input_ports_for_config(cls, config: NodeConfig) -> dict[str, ports.PortSpec]:
        result = dict(super().input_ports_for_config(config))
        conversion = str(config.get("conversion") or "message_to_text")
        if conversion in CONVERSIONS:
            result["input"] = CONVERSIONS[conversion][0]
        return result

    @classmethod
    def outputs_for_config(cls, config: NodeConfig) -> list[Output]:
        conversion = str(config.get("conversion") or "message_to_text")
        port = CONVERSIONS.get(conversion, (ports.ANY, ports.ANY))[1]
        return [Output(name="output", display_name="Output", port=port)]

    def build(self, ctx: BuildContext) -> NodeFn:
        from langgraph_agent_builder.sdk.templating import render_jinja

        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            conversion = str(ctx.get_field("conversion") or "message_to_text")
            value = ctx.get_input(state, "input")
            out: Any
            match conversion:
                case "message_to_text":
                    out = message_text(value)
                case "text_to_message":
                    out = Message(role="user", content=str(value or ""))
                case "documents_to_text":
                    template = str(ctx.get_field("documents_template") or "{{ page_content }}")
                    blocks = []
                    for doc in value or []:
                        if isinstance(doc, Document):
                            blocks.append(
                                render_jinja(
                                    template,
                                    {"page_content": doc.page_content, "metadata": doc.metadata},
                                )
                            )
                        elif isinstance(doc, dict):
                            blocks.append(
                                render_jinja(
                                    template,
                                    {
                                        "page_content": doc.get("page_content", ""),
                                        "metadata": doc.get("metadata", {}),
                                    },
                                )
                            )
                        else:
                            blocks.append(str(doc))
                    out = "\n\n".join(blocks)
                case "json_to_text":
                    out = json.dumps(value, indent=2, ensure_ascii=False, default=str)
                case "text_to_json":
                    try:
                        out = json.loads(str(value or "{}"))
                    except json.JSONDecodeError:
                        out = {"raw": str(value)}
                case "table_to_json":
                    out = {"rows": value} if isinstance(value, list) else (value or {})
                case "json_to_table":
                    rows = value.get("rows") if isinstance(value, dict) else value
                    out = rows if isinstance(rows, list) else ([value] if value else [])
                case _:
                    out = value
            return {"output": out}

        return node


class JsonExtract(Component):
    component_id = "lab.data.json_extract"
    legacy = True
    display_name = "JSON Extract"
    description = "Extract a value from Json via JSONPath."
    icon = "filter"
    category = "data"

    inputs = [
        fields.StrInput(
            name="path", display_name="JSONPath", placeholder="$.items[0].name", required=True
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.JSON),
    ]
    outputs = [
        Output(name="value", display_name="Value", port=ports.JSON),
        Output(name="text", display_name="Text", port=ports.TEXT),
    ]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            from jsonpath_ng import parse as jsonpath_parse

            expr = jsonpath_parse(str(ctx.get_field("path") or "$"))
            source = ctx.get_input(state, "input") or {}
            matches = [m.value for m in expr.find(source)]
            value: Any = matches[0] if len(matches) == 1 else matches
            return {
                "value": value if isinstance(value, dict) else {"value": value},
                "text": value if isinstance(value, str) else json.dumps(value, default=str),
            }

        return node


class Parser(Component):
    component_id = "lab.data.parser"
    legacy = True
    display_name = "Parser"
    description = "Regex/split text parsing into Json."
    icon = "scissors"
    category = "data"

    inputs = [
        fields.TabInput(
            name="mode", display_name="Mode", options=["regex", "split"], default="regex"
        ),
        fields.StrInput(
            name="pattern",
            display_name="Pattern / Separator",
            info="regex with named groups, or the split separator.",
            required=True,
        ),
        fields.HandleField(name="input", display_name="Input", as_port=ports.TEXT),
    ]
    outputs = [Output(name="json", display_name="Json", port=ports.JSON)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            text = str(ctx.get_input(state, "input") or "")
            pattern = str(ctx.get_field("pattern") or "")
            if ctx.get_field("mode") == "split":
                return {"json": {"parts": text.split(pattern) if pattern else [text]}}
            match = re.search(pattern, text)
            if match is None:
                return {"json": {"matched": False}}
            groups = match.groupdict() or {str(i): g for i, g in enumerate(match.groups(), start=1)}
            return {"json": {"matched": True, **groups}}

        return node
