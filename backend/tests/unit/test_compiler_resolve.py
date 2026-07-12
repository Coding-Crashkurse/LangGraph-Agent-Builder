"""Unit tests for langgraph_agent_builder.compiler.resolve (P2): $var/$secret/$vectorstore
resolution, credential-leak guard, tweaks, and field-level diagnostics."""

from __future__ import annotations

from typing import Any

from langgraph_agent_builder.compiler import parse as parse_pass
from langgraph_agent_builder.compiler.resolve import EnvVariablesProvider, resolve, snapshot_digest
from langgraph_agent_builder.schema.diagnostics import Diagnostic, DiagnosticCode
from langgraph_agent_builder.schema.flowspec import FlowSpec
from langgraph_agent_builder.sdk import BuildContext, Component, fields
from langgraph_agent_builder.sdk.component import NodeFn, SecretRef
from langgraph_agent_builder.sdk.ports import VectorStoreHandle
from langgraph_agent_builder.sdk.registry import ComponentRegistry, get_registry
from tests.conftest import hello_spec


class _Vars:
    def __init__(
        self, variables: dict[str, str] | None = None, secrets: dict[str, str] | None = None
    ) -> None:
        self._vars = variables or {}
        self._secrets = secrets or {}

    def get_var(self, name: str) -> str | None:
        return self._vars.get(name)

    def get_secret(self, name: str) -> str | None:
        return self._secrets.get(name)

    def has_var(self, name: str) -> bool:
        return name in self._vars

    def has_secret(self, name: str) -> bool:
        return name in self._secrets


class _FallbackVars(_Vars):
    def env_fallback(self, name: str) -> str | None:
        return "from-env" if name == "needs_fallback" else None


class _SecretComp(Component):
    """Minimal component with a Secret field, to exercise the $secret guard."""

    component_id = "test.secret_comp"
    display_name = "Secret Comp"
    category = "testing"
    inputs = [fields.SecretInput(name="api_key", display_name="API Key")]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {}

        return node


def _secret_registry() -> ComponentRegistry:
    registry = ComponentRegistry()
    registry.register(_SecretComp)
    return registry


def _spec(component_id: str, config: dict[str, Any], version: str = "1.0.0") -> FlowSpec:
    raw = {
        "schema_version": "1",
        "flow": {"name": "t", "slug": "t"},
        "nodes": [
            {
                "id": "n",
                "component_id": component_id,
                "component_version": version,
                "config": config,
                "position": {"x": 0, "y": 0},
            }
        ],
        "edges": [],
    }
    spec, diags = parse_pass.parse(raw)
    assert spec is not None, diags
    return spec


def _codes(diags: list[Diagnostic]) -> list[DiagnosticCode]:
    return [d.code for d in diags]


# --------------------------------------------------------------- $var


def test_var_resolves_and_unknown_key_tolerated() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": ["ok"], "greeting": {"$var": "g"}})
    ir, diags = resolve(spec, get_registry(), _Vars(variables={"g": "hello"}))
    # unknown key still resolves & compiles, but is flagged (W303, warning only)
    assert _codes(diags) == [DiagnosticCode.W303]
    assert diags[0].field == "greeting"
    assert diags[0].severity == "warning"
    assert ir.nodes["n"].config["greeting"] == "hello"  # $var replaced
    assert ir.nodes["n"].config["replies"] == ["ok"]


def test_missing_var_is_e012() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": ["ok"], "greeting": {"$var": "gone"}})
    _ir, diags = resolve(spec, get_registry(), _Vars())
    diag = next(d for d in diags if d.code == DiagnosticCode.E012)
    assert "gone" in diag.message
    assert diag.field == "greeting"


def test_var_env_fallback_used_when_absent() -> None:
    spec = _spec(
        "lab.testing.fake_llm", {"replies": ["ok"], "greeting": {"$var": "needs_fallback"}}
    )
    ir, diags = resolve(spec, get_registry(), _FallbackVars())
    assert DiagnosticCode.E012 not in _codes(diags)
    assert ir.nodes["n"].config["greeting"] == "from-env"


# --------------------------------------------------------------- $secret


def test_secret_resolves_to_secretref() -> None:
    spec = _spec("test.secret_comp", {"api_key": {"$secret": "K"}})
    ir, diags = resolve(spec, _secret_registry(), _Vars(secrets={"K": "sk-abc"}))
    assert DiagnosticCode.E012 not in _codes(diags)
    assert DiagnosticCode.E014 not in _codes(diags)
    value = ir.nodes["n"].config["api_key"]
    assert isinstance(value, SecretRef)
    assert str(value) == "sk-abc"


def test_missing_secret_is_e012() -> None:
    spec = _spec("test.secret_comp", {"api_key": {"$secret": "GONE"}})
    _ir, diags = resolve(spec, _secret_registry(), _Vars())
    diag = next(d for d in diags if d.code == DiagnosticCode.E012)
    assert "GONE" in diag.message


# --------------------------------------------------------------- $vectorstore


def test_vectorstore_ref_resolves_to_handle() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": ["ok"], "vs": {"$vectorstore": "myconn"}})
    ir, diags = resolve(spec, get_registry(), _Vars(), vectorstore_names={"myconn"})
    assert DiagnosticCode.E013 not in _codes(diags)
    handle = ir.nodes["n"].config["vs"]
    assert isinstance(handle, VectorStoreHandle)
    assert handle.connection == "myconn"


def test_unknown_vectorstore_is_e013() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": ["ok"], "vs": {"$vectorstore": "nope"}})
    _ir, diags = resolve(spec, get_registry(), _Vars(), vectorstore_names=set())
    diag = next(d for d in diags if d.code == DiagnosticCode.E013)
    assert "nope" in diag.message


# --------------------------------------------------------------- tweaks


def test_tweak_unknown_field_is_e011() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": ["ok"]})
    _ir, diags = resolve(spec, get_registry(), _Vars(), tweaks={"n": {"does_not_exist": 1}})
    diag = next(d for d in diags if d.code == DiagnosticCode.E011)
    assert "does_not_exist" in diag.message


def test_tweak_on_secret_field_is_rejected() -> None:
    spec = _spec("test.secret_comp", {})
    _ir, diags = resolve(spec, _secret_registry(), _Vars(), tweaks={"n": {"api_key": "leaked"}})
    diag = next(d for d in diags if d.code == DiagnosticCode.E011)
    assert "not tweakable" in diag.message


# --------------------------------------------------------------- deprecated field (W301)


class _Deprecated(Component):
    component_id = "test.deprecated_comp"
    display_name = "Deprecated"
    category = "testing"
    inputs = [fields.StrInput(name="old", display_name="Old", deprecated=True)]

    def build(self, ctx: BuildContext) -> NodeFn:
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            return {}

        return node


def test_deprecated_field_in_use_is_w301() -> None:
    registry = ComponentRegistry()
    registry.register(_Deprecated)
    spec = _spec("test.deprecated_comp", {"old": "still-set"}, version=_Deprecated.version)
    _ir, diags = resolve(spec, registry, _Vars())
    diag = next(d for d in diags if d.code == DiagnosticCode.W301)
    assert diag.field == "old"


# --------------------------------------------------------------- more branches


def test_env_variables_provider_lookup_precedence() -> None:
    provider = EnvVariablesProvider({"LAB_VAR_FOO": "bar", "LAB_CRED_KEY": "sk", "PLAIN": "p"})
    assert provider.get_var("foo") == "bar"  # prefixed form wins
    assert provider.get_var("PLAIN") == "p"  # raw fallback
    assert provider.has_var("foo") is True
    assert provider.has_var("missing") is False
    assert provider.get_secret("key") == "sk"
    assert provider.has_secret("key") is True
    assert provider.has_secret("absent") is False


def test_unknown_component_is_e002() -> None:
    spec = _spec("lab.nope.missing", {})
    ir, diags = resolve(spec, get_registry(), _Vars())
    assert DiagnosticCode.E002 in _codes(diags)
    assert "n" not in ir.nodes  # skipped, no NodeIR built


def test_version_mismatch_migrates_with_w302() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": ["ok"]}, version="0.9.0")
    ir, diags = resolve(spec, get_registry(), _Vars())
    assert DiagnosticCode.W302 in _codes(diags)
    assert ir.nodes["n"].migrated_from == "0.9.0"


def test_tweak_applies_to_valid_field() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": ["original"]})
    ir, diags = resolve(spec, get_registry(), _Vars(), tweaks={"n": {"replies": ["tweaked"]}})
    assert DiagnosticCode.E011 not in _codes(diags)
    assert ir.nodes["n"].config["replies"] == ["tweaked"]


def test_secret_in_non_secret_field_is_e014() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": {"$secret": "K"}})
    _ir, diags = resolve(spec, get_registry(), _Vars(secrets={"K": "sk"}))
    diag = next(d for d in diags if d.code == DiagnosticCode.E014)
    assert diag.field == "replies"


def test_nested_secret_in_non_secret_field_is_e014_and_unresolved() -> None:
    """The credential-leak guard recurses into containers — nesting the ref
    must not bypass E014, and the plaintext must never be resolved (§10.5)."""
    spec = _spec("lab.testing.fake_llm", {"replies": [{"auth": {"$secret": "K"}}]})
    ir, diags = resolve(spec, get_registry(), _Vars(secrets={"K": "sk-leak"}))
    diag = next(d for d in diags if d.code == DiagnosticCode.E014)
    assert diag.field == "replies"
    assert ir.nodes["n"].config["replies"] == [{"auth": None}]  # ref NOT resolved


def test_nested_secret_in_secret_field_is_allowed() -> None:
    spec = _spec("test.secret_comp", {"api_key": {"$secret": "K"}})
    _ir, diags = resolve(spec, _secret_registry(), _Vars(secrets={"K": "sk"}))
    assert DiagnosticCode.E014 not in _codes(diags)


def test_field_schema_violation_is_e011() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": "not-a-list"})
    _ir, diags = resolve(spec, get_registry(), _Vars())
    assert DiagnosticCode.E011 in _codes(diags)


def test_fallback_returning_none_still_reports_e012() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": ["ok"], "greeting": {"$var": "other"}})
    _ir, diags = resolve(spec, get_registry(), _FallbackVars())
    assert DiagnosticCode.E012 in _codes(diags)  # fallback returned None


# --------------------------------------------------------------- snapshot digest


def test_snapshot_digest_tracks_referenced_values() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": ["ok"], "greeting": {"$var": "g"}})
    one_a = snapshot_digest(spec, _Vars(variables={"g": "one"}))
    one_b = snapshot_digest(spec, _Vars(variables={"g": "one"}))
    two = snapshot_digest(spec, _Vars(variables={"g": "two"}))
    assert one_a == one_b
    assert one_a != two  # edited variable → different compile-cache key


def test_snapshot_digest_tracks_tweaks_and_vectorstores() -> None:
    spec = _spec("lab.testing.fake_llm", {"replies": ["ok"], "vs": {"$vectorstore": "conn"}})
    base = snapshot_digest(spec, _Vars(), vectorstore_names={"conn"})
    assert snapshot_digest(spec, _Vars(), vectorstore_names=set()) != base  # store deleted
    assert snapshot_digest(spec, _Vars(), tweaks={"n": {"replies": ["t"]}}) != snapshot_digest(
        spec, _Vars()
    )


def test_snapshot_digest_uses_env_fallback() -> None:
    spec = _spec("lab.testing.fake_llm", {"greeting": {"$var": "needs_fallback"}})
    assert snapshot_digest(spec, _FallbackVars()) != snapshot_digest(spec, _Vars())


def test_edges_receive_resolved_ports() -> None:
    spec, _ = parse_pass.parse(hello_spec())
    assert spec is not None
    ir, _diags = resolve(spec, get_registry(), _Vars())
    e1 = next(e for e in ir.edges if e.id == "e1")
    assert e1.source_port is not None  # start.message
    assert e1.target_port is not None  # fake.input


def test_edges_touching_skipped_nodes_leave_ports_unset() -> None:
    raw = {
        "schema_version": "1",
        "flow": {"name": "t", "slug": "t"},
        "nodes": [
            {
                "id": "a",
                "component_id": "lab.testing.fake_llm",
                "component_version": "1.0.0",
                "config": {"replies": ["ok"]},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "b",
                "component_id": "lab.nope.missing",  # unknown → NodeIR skipped (E002)
                "component_version": "1.0.0",
                "config": {},
                "position": {"x": 0, "y": 0},
            },
        ],
        "edges": [
            {
                "id": "ab",
                "kind": "data",
                "source": {"node": "a", "output": "message"},
                "target": {"node": "b", "input": "input"},
            },
            {
                "id": "ba",
                "kind": "data",
                "source": {"node": "b", "output": "message"},
                "target": {"node": "a", "input": "input"},
            },
        ],
    }
    spec, _ = parse_pass.parse(raw)
    assert spec is not None
    ir, diags = resolve(spec, get_registry(), _Vars())
    assert DiagnosticCode.E002 in _codes(diags)
    ab = next(e for e in ir.edges if e.id == "ab")
    ba = next(e for e in ir.edges if e.id == "ba")
    assert ab.target_port is None  # target node was skipped
    assert ba.source_port is None  # source node was skipped
