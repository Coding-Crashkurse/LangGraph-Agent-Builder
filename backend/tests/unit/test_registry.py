"""Unit tests for langgraph_agent_builder.sdk.registry (component discovery, SPEC §4.8).

Exercises registration invariants (duplicate detection, missing id), filesystem
discovery from a temp component dir (LAB_COMPONENTS_PATH style), the
testing-category filter, error isolation (broken/missing sources become
diagnostics, never crashes), and the fingerprint/etag identity helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from langgraph_agent_builder.sdk.component import BuildContext, Component, NodeFn
from langgraph_agent_builder.sdk.registry import (
    ComponentRegistry,
    DuplicateComponentError,
    get_registry,
    reset_registry,
)

if TYPE_CHECKING:
    from pathlib import Path


class _Alpha(Component):
    component_id = "test.reg.alpha"
    version = "1.0.0"
    category = "data"

    def build(self, ctx: BuildContext) -> NodeFn:
        async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            return {}

        return run


class _AlphaClone(Component):
    """Same component_id as _Alpha but a distinct class → duplicate."""

    component_id = "test.reg.alpha"
    version = "2.0.0"
    category = "data"

    def build(self, ctx: BuildContext) -> NodeFn:
        async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            return {}

        return run


class _NoId(Component):
    """No component_id set → register must reject it."""

    def build(self, ctx: BuildContext) -> NodeFn:
        async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            return {}

        return run


class _LegacyBeta(Component):
    component_id = "test.reg.beta"
    version = "1.0.0"
    category = "data"
    legacy = True

    def build(self, ctx: BuildContext) -> NodeFn:
        async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            return {}

        return run


# ----------------------------------------------------------------- registration
def test_register_and_get() -> None:
    reg = ComponentRegistry()
    reg.register(_Alpha, origin="unit")
    assert reg.get("test.reg.alpha") is _Alpha
    assert reg.origins["test.reg.alpha"] == "unit"
    assert reg.get("missing") is None


def test_register_same_class_twice_is_idempotent() -> None:
    reg = ComponentRegistry()
    reg.register(_Alpha)
    reg.register(_Alpha)  # identical class → no error
    assert reg.origins["test.reg.alpha"] == "manual"


def test_register_duplicate_id_raises() -> None:
    reg = ComponentRegistry()
    reg.register(_Alpha, origin="first")
    with pytest.raises(DuplicateComponentError, match="duplicate component_id"):
        reg.register(_AlphaClone, origin="second")


def test_register_without_component_id_raises() -> None:
    reg = ComponentRegistry()
    with pytest.raises(ValueError, match="no component_id"):
        reg.register(_NoId)


def test_all_orders_and_filters_legacy() -> None:
    reg = ComponentRegistry()
    reg.register(_LegacyBeta)
    reg.register(_Alpha)
    assert [c.component_id for c in reg.all()] == ["test.reg.alpha", "test.reg.beta"]
    assert [c.component_id for c in reg.all(include_legacy=False)] == ["test.reg.alpha"]


# ----------------------------------------------------------------- fingerprint
def test_fingerprint_and_etag() -> None:
    reg = ComponentRegistry()
    reg.register(_Alpha)
    fp = reg.fingerprint()
    assert len(fp) == 16
    assert all(ch in "0123456789abcdef" for ch in fp)
    assert reg.etag() == f'W/"{fp}"'


def test_fingerprint_changes_with_contents() -> None:
    empty = ComponentRegistry().fingerprint()
    reg = ComponentRegistry()
    reg.register(_Alpha)
    assert reg.fingerprint() != empty


# ------------------------------------------------------------------- discovery
_COMPONENT_SRC = """
from typing import Any
from langgraph_agent_builder.sdk.component import BuildContext, Component, NodeFn


class Widget(Component):
    component_id = "test.scan.widget"
    version = "1.0.0"
    category = "data"

    def build(self, ctx: BuildContext) -> NodeFn:
        async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            return {}
        return run


class LabTool(Component):
    component_id = "test.scan.labtool"
    version = "1.0.0"
    category = "testing"

    def build(self, ctx: BuildContext) -> NodeFn:
        async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            return {}
        return run
"""

_HIDDEN_SRC = """
from typing import Any
from langgraph_agent_builder.sdk.component import BuildContext, Component, NodeFn


class Hidden(Component):
    component_id = "test.scan.hidden"
    version = "1.0.0"
    category = "data"

    def build(self, ctx: BuildContext) -> NodeFn:
        async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            return {}
        return run
"""


def _write_dir(tmp_path: Path) -> Path:
    root = tmp_path / "components"
    cat = root / "mycat"
    cat.mkdir(parents=True)
    (cat / "widget.py").write_text(_COMPONENT_SRC, encoding="utf-8")
    (cat / "_hidden.py").write_text(_HIDDEN_SRC, encoding="utf-8")  # underscore → skipped
    return root


def test_scan_dir_registers_and_skips_underscore(tmp_path: Path) -> None:
    root = _write_dir(tmp_path)
    reg = ComponentRegistry()  # include_testing defaults True
    reg.discover(extra_dirs=[root])

    assert reg.get("test.scan.widget") is not None
    assert reg.get("test.scan.labtool") is not None  # testing kept by default
    assert reg.get("test.scan.hidden") is None  # underscore file skipped
    assert reg.origins["test.scan.widget"].endswith("widget.py")
    assert not [d for d in reg.diagnostics if "widget" in d.origin]


def test_scan_dir_excludes_testing_when_disabled(tmp_path: Path) -> None:
    root = _write_dir(tmp_path)
    reg = ComponentRegistry(include_testing=False)
    reg.discover(extra_dirs=[root])
    assert reg.get("test.scan.widget") is not None
    assert reg.get("test.scan.labtool") is None  # testing category filtered out


def test_broken_module_becomes_diagnostic_no_crash(tmp_path: Path) -> None:
    root = tmp_path / "broken"
    root.mkdir()
    (root / "oops.py").write_text("def broken(:\n  syntax error", encoding="utf-8")
    reg = ComponentRegistry()
    reg.discover(extra_dirs=[root])  # must not raise
    assert any(d.origin.endswith("oops.py") for d in reg.diagnostics)
    assert reg.get("test.scan.widget") is None


def test_missing_dir_records_diagnostic(tmp_path: Path) -> None:
    reg = ComponentRegistry()
    reg.discover(extra_dirs=[tmp_path / "nope"])
    assert any(d.message == "components dir not found" for d in reg.diagnostics)


_TREE_GOOD_SRC = """
from typing import Any
from langgraph_agent_builder.sdk.component import BuildContext, Component, NodeFn


class TreeGood(Component):
    component_id = "test.tree.good"
    version = "1.0.0"
    category = "data"

    def build(self, ctx: BuildContext) -> NodeFn:
        async def run(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            return {}
        return run
"""


def test_register_module_tree_isolates_broken_submodule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    pkg = tmp_path / "brokentreepkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "good.py").write_text(_TREE_GOOD_SRC, encoding="utf-8")
    (pkg / "bad.py").write_text("import totally_missing_module_xyz\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    module = importlib.import_module("brokentreepkg")
    reg = ComponentRegistry()
    reg._register_module_tree(module, origin="entry-point:tree")

    # the healthy submodule registered; the broken one is isolated as a diagnostic
    assert reg.get("test.tree.good") is not None
    assert any("bad" in d.origin for d in reg.diagnostics)


# ------------------------------------------------------------- default registry
def test_get_registry_is_cached_and_populated() -> None:
    first = get_registry()
    second = get_registry()
    assert first is second  # lazy singleton
    assert first.components  # built-ins discovered
    assert first.get("lab.io.start") is not None


def test_reset_registry_forces_rediscovery() -> None:
    before = get_registry()
    reset_registry()
    after = get_registry()
    assert after is not before
    assert after.components  # rediscovered built-ins
