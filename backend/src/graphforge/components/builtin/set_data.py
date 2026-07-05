"""Write literal or templated values into state['data'] (glue/debugging)."""

from typing import Any

from pydantic import Field

from graphforge.components.base import BaseComponent, BuildContext, ComponentConfig, NodeFn
from graphforge.components.registry import register
from graphforge.components.templating import render_template


class SetDataConfig(ComponentConfig):
    values: dict[str, str] = Field(
        default_factory=dict,
        description="Keys written into state.data; values support {templates}.",
    )


@register
class SetData(BaseComponent):
    name = "set_data"
    display_name = "Set Data"
    description = "Writes literal/templated values into the shared data dict."
    category = "io"
    version = 1
    config_model = SetDataConfig
    state_reads = ["messages", "data", "route"]
    state_writes = ["data"]

    def build(self, config: SetDataConfig, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], _config: Any) -> dict[str, Any]:
            return {
                "data": {key: render_template(value, state) for key, value in config.values.items()}
            }

        return node
