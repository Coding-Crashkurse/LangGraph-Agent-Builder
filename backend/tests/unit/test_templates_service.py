"""Unit tests for lga.services.templates (SPEC §9.9).

Pure module over the bundled STARTER_FLOWS — no DB needed.
"""

from __future__ import annotations

from lga.services import templates
from lga.services.bootstrap import STARTER_FLOWS


def test_list_templates_metadata() -> None:
    listed = templates.list_templates()
    assert len(listed) == len(STARTER_FLOWS)
    by_id = {t["id"]: t for t in listed}
    hello = by_id["starter-hello"]
    assert hello["name"] == "Starter: Hello"
    assert hello["node_count"] == 3
    assert hello["icon"] == "bot"  # default when the flow declares no icon
    # metadata only — the raw node/edge spec must not leak into the gallery card
    assert "nodes" not in hello
    assert "edges" not in hello


def test_get_template_returns_independent_copy() -> None:
    spec = templates.get_template("starter-hello")
    assert spec is not None
    assert spec["flow"]["slug"] == "starter-hello"
    # mutating the returned spec must not corrupt the shared STARTER_FLOWS source
    spec["flow"]["name"] = "MUTATED"
    again = templates.get_template("starter-hello")
    assert again is not None
    assert again["flow"]["name"] == "Starter: Hello"


def test_get_template_unknown() -> None:
    assert templates.get_template("does-not-exist") is None


def test_instantiate_strips_prefixes() -> None:
    spec = templates.instantiate("starter-hello", existing_slugs=set())
    assert spec is not None
    assert spec["flow"]["slug"] == "hello"
    assert spec["flow"]["name"] == "Hello"  # "Starter: " stripped


def test_instantiate_disambiguates_slug() -> None:
    spec = templates.instantiate("starter-hello", existing_slugs={"hello", "hello-2"})
    assert spec is not None
    assert spec["flow"]["slug"] == "hello-3"


def test_instantiate_unknown_template() -> None:
    assert templates.instantiate("nope", existing_slugs=set()) is None
