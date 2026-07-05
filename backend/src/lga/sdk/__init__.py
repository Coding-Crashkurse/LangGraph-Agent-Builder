"""Component SDK — importable standalone, never imports FastAPI/DB (SPEC §2.7)."""

from lga.sdk import fields, ports
from lga.sdk.component import BuildContext, Component, NodeConfig, NodeKind
from lga.sdk.outputs import Output
from lga.sdk.runtime import NodeContext, RunContext, get_run_context

__all__ = [
    "BuildContext",
    "Component",
    "NodeConfig",
    "NodeContext",
    "NodeKind",
    "Output",
    "RunContext",
    "fields",
    "get_run_context",
    "ports",
]
