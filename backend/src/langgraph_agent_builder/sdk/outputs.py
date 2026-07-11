"""Output declarations (SPEC §4.5)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator

from langgraph_agent_builder.sdk.ports import PortSpec


class Output(BaseModel):
    name: str  # state channel suffix; stable
    display_name: str = ""
    port: PortSpec
    method: str | None = None  # multi-output components: method computing ONLY this output
    group: str | None = None
    deprecated: bool = False

    @model_validator(mode="after")
    def _default_display(self) -> Output:
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()
        return self

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "port": self.port.model_dump(mode="json"),
            "method": self.method,
            "group": self.group,
            "deprecated": self.deprecated,
        }
