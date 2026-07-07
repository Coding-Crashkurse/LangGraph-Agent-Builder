"""Set Data — writes literal/jinja-templated values into `data` (SPEC §12.1)."""

from __future__ import annotations

from typing import Any

from lga.sdk import Component, Output, fields, ports
from lga.sdk.templating import last_message_text, render_jinja


class SetData(Component):
    component_id = "lga.io.set_data"
    display_name = "Set Data"
    description = "Write literal or jinja-templated values into the shared data dict."
    icon = "database"
    category = "io"

    inputs = [
        fields.TableInput(
            name="entries",
            display_name="Entries",
            info="Rows of key + template. Templates are sandboxed jinja over "
            "{data, message, route}.",
            columns=[
                fields.ColumnSpec(name="key", type="str"),
                fields.ColumnSpec(name="template", type="str"),
            ],
            required=True,
        ),
        # trigger port so Set Data can be chained anywhere in the control flow
        fields.HandleField(name="input", display_name="Input", as_port=ports.ANY),
    ]
    outputs = [Output(name="data", display_name="Data", port=ports.JSON)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            variables = {
                "data": dict(state.get("data") or {}),
                "message": last_message_text(state),
                "route": dict(state.get("route") or {}),
            }
            written: dict[str, Any] = {}
            for row in ctx.get_field("entries") or []:
                key = str(row.get("key", "")).strip()
                if not key:
                    continue
                written[key] = render_jinja(str(row.get("template", "")), variables)
            return {"data": written}

        return node
