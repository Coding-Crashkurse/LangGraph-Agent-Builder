"""Unit tests for lga.sdk.dynamic (SPEC §9.2): sync/async on_field_change
dispatch, the timeout bound, init-failure translation, and hook exceptions
propagating unchanged — all HTTP-free (lga.sdk never imports FastAPI)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from lga.sdk.component import BuildContext, Component, NodeConfig, NodeFn
from lga.sdk.dynamic import ComponentInitError, invoke_field_change


class _SyncComp(Component):
    component_id = "test.dynamic.sync"

    def build(self, ctx: BuildContext) -> NodeFn:  # pragma: no cover - unused
        raise NotImplementedError


class _AsyncComp(Component):
    component_id = "test.dynamic.async"

    def build(self, ctx: BuildContext) -> NodeFn:  # pragma: no cover - unused
        raise NotImplementedError

    async def on_field_change(  # type: ignore[override]
        self, config: NodeConfig, field_name: str, value: Any
    ) -> NodeConfig:
        return {**config, field_name: value, "touched": "async"}


class _SlowComp(_AsyncComp):
    component_id = "test.dynamic.slow"

    async def on_field_change(self, config: NodeConfig, field_name: str, value: Any) -> NodeConfig:
        await asyncio.sleep(30)
        return config  # pragma: no cover - never reached


class _BadInitComp(_SyncComp):
    component_id = "test.dynamic.badinit"

    def __init__(self) -> None:
        raise RuntimeError("boom in __init__")


class _RaisingHookComp(_SyncComp):
    component_id = "test.dynamic.raises"

    def on_field_change(self, config: NodeConfig, field_name: str, value: Any) -> NodeConfig:
        raise KeyError("hook exploded")


async def test_sync_hook_runs_off_loop_and_roundtrips_value() -> None:
    # default Component.on_field_change writes the value into a config copy
    config = await invoke_field_change(_SyncComp, "model", "gpt-x", {"kept": 1})
    assert config == {"kept": 1, "model": "gpt-x"}


async def test_async_hook_is_awaited() -> None:
    config = await invoke_field_change(_AsyncComp, "f", 2, {})
    assert config == {"f": 2, "touched": "async"}


async def test_timeout_raises_plain_timeout_error() -> None:
    with pytest.raises(TimeoutError):
        await invoke_field_change(_SlowComp, "f", 1, {}, timeout_s=0.05)


async def test_init_failure_raises_component_init_error() -> None:
    with pytest.raises(ComponentInitError, match=r"test\.dynamic\.badinit"):
        await invoke_field_change(_BadInitComp, "f", 1, {})


async def test_hook_exceptions_propagate_unchanged() -> None:
    with pytest.raises(KeyError, match="hook exploded"):
        await invoke_field_change(_RaisingHookComp, "f", 1, {})
