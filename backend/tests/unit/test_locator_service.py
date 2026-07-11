"""Unit tests for langgraph_agent_builder.services.locator — the process-wide service locator."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from langgraph_agent_builder.services import locator


@pytest.fixture(autouse=True)
def _restore_locator() -> Iterator[None]:
    """The locator is process-global; snapshot and restore it around each test."""
    saved = locator.get_services()
    try:
        yield
    finally:
        locator.set_services(saved)


def test_set_and_get_roundtrip() -> None:
    sentinel = object()
    locator.set_services(sentinel)
    assert locator.get_services() is sentinel


def test_require_services_raises_without_context() -> None:
    locator.set_services(None)
    with pytest.raises(RuntimeError, match="file_loader requires a running lab server"):
        locator.require_services("file_loader")


def test_require_services_returns_current() -> None:
    sentinel = object()
    locator.set_services(sentinel)
    assert locator.require_services("flow_as_tool") is sentinel
