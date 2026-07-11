"""CheckpointerFactory first-call race (SPEC §6.3): concurrent get() builds once."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from lga.runtime.checkpoint import CheckpointerFactory

if TYPE_CHECKING:
    import pytest

    from lga.services.settings import Settings


async def test_concurrent_first_get_builds_single_checkpointer(
    sqlite_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = CheckpointerFactory(sqlite_settings)
    builds = 0
    original = factory._build

    async def counting_build() -> Any:
        nonlocal builds
        builds += 1
        await asyncio.sleep(0.05)  # widen the race window
        return await original()

    monkeypatch.setattr(factory, "_build", counting_build)
    try:
        first, second = await asyncio.gather(factory.get(), factory.get())
        assert first is second
        assert builds == 1  # the lock serialized construction
    finally:
        await factory.aclose()
