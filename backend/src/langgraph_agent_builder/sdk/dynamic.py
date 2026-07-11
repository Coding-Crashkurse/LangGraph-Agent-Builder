"""Dynamic-form dispatch (SPEC §9.2): ``on_field_change`` outside the HTTP layer.

The Studio route translates the plain exceptions raised here into HTTP codes;
this module stays importable standalone — ``lga.sdk`` never imports FastAPI
(SPEC §2.7).
"""

from __future__ import annotations

import asyncio
from typing import Any

from lga.errors import LgaValueError
from lga.sdk.component import Component, NodeConfig

DEFAULT_FIELD_CHANGE_TIMEOUT_S = 10.0


class ComponentInitError(LgaValueError):
    """The component's ``__init__`` failed before ``on_field_change`` could run."""


async def invoke_field_change(
    component_cls: type[Component],
    field: str,
    value: Any,
    config: NodeConfig,
    timeout_s: float = DEFAULT_FIELD_CHANGE_TIMEOUT_S,
) -> NodeConfig:
    """Instantiate ``component_cls`` and dispatch its ``on_field_change`` hook.

    A sync hook runs on a worker thread so a slow author callback can never
    block the event loop; an async hook is awaited directly. Either way the
    call is bounded by ``timeout_s`` and raises ``TimeoutError`` when exceeded.
    Instantiation failures raise ``ComponentInitError``; the hook's own
    exceptions propagate unchanged.
    """
    try:
        instance = component_cls()
    except Exception as exc:
        raise ComponentInitError(
            f"component {component_cls.component_id!r} failed to initialize: {exc}"
        ) from exc
    hook = instance.on_field_change
    result: NodeConfig
    if asyncio.iscoroutinefunction(hook):
        result = await asyncio.wait_for(hook(config, field, value), timeout=timeout_s)
    else:
        result = await asyncio.wait_for(
            asyncio.to_thread(hook, config, field, value), timeout=timeout_s
        )
    return result
