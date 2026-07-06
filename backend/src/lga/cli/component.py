"""`lga component new` — scaffold a custom component package (SPEC §2.6)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lga.cli._common import EXIT_USAGE, console, err_console

PYPROJECT_TPL = """\
[project]
name = "{pkg}"
version = "0.1.0"
description = "Custom lga component: {display}"
requires-python = ">=3.12"
dependencies = ["lga"]

[project.entry-points."lga.components"]
{name} = "{pkg}"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{pkg}"]
"""

COMPONENT_TPL = '''\
"""{display} — custom lga component."""

from typing import Any

from lga.sdk import Component, Output, fields, ports


class {cls}(Component):
    component_id = "{pkg}.{category}.{name}"
    display_name = "{display}"
    description = "Describe what {display} does — agents route on this text."
    icon = "box"
    category = "{category}"

    inputs = [
        fields.HandleField(name="input", display_name="Input", as_port=ports.TEXT),
        fields.StrInput(name="option", display_name="Option", default=""),
    ]
    outputs = [Output(name="text", display_name="Text", port=ports.TEXT)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            value = str(ctx.get_input(state, "input") or "")
            return {{"text": value}}

        return node
'''

TEST_TPL = """\
import pytest

from lga.sdk.testing import ComponentTestHarness

from {pkg} import {cls}


def test_descriptor_snapshot():
    descriptor = ComponentTestHarness().render_descriptor({cls})
    assert descriptor["component_id"] == "{pkg}.{category}.{name}"
    assert descriptor["outputs"]


@pytest.mark.asyncio
async def test_build_and_run():
    node = ComponentTestHarness().build({cls}, config={{}}, ports={{"input": "hi"}})
    result = await node()
    assert result["text"] == "hi"
"""


def component_new(
    name: Annotated[str, typer.Argument(help="snake_case component name")],
    category: Annotated[str, typer.Option(help="Palette category")] = "data",
    path: Annotated[Path, typer.Option(help="Target directory")] = Path("./components"),
) -> None:
    """Scaffold an installable component package with entry point + harness test."""
    if not name.isidentifier() or name != name.lower():
        err_console.print("[red]name must be snake_case[/red]")
        raise typer.Exit(EXIT_USAGE)
    pkg = f"lga_{name}"
    cls = "".join(part.title() for part in name.split("_"))
    display = name.replace("_", " ").title()
    root = path / pkg
    if root.exists():
        err_console.print(f"[red]{root} already exists[/red]")
        raise typer.Exit(EXIT_USAGE)
    src = root / "src" / pkg
    src.mkdir(parents=True)
    (root / "tests").mkdir()
    fmt = dict(pkg=pkg, cls=cls, name=name, display=display, category=category)
    (root / "pyproject.toml").write_text(PYPROJECT_TPL.format(**fmt), encoding="utf-8")
    (src / "__init__.py").write_text(COMPONENT_TPL.format(**fmt), encoding="utf-8")
    (root / "tests" / f"test_{name}.py").write_text(TEST_TPL.format(**fmt), encoding="utf-8")
    console.print(f"[green]component package created:[/green] {root}")
    console.print(f"install it with: [bold]uv pip install -e {root}[/bold] and restart lga")
