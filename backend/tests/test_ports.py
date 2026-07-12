"""Port compatibility matrix (golden table) + coercions (SPEC §15.1)."""

from __future__ import annotations

import pytest

from langgraph_agent_builder.sdk.ports import (
    ANY,
    DOCUMENTS,
    JSON,
    MESSAGE,
    MESSAGES,
    ROUTE,
    TEXT,
    TOOLSET,
    Message,
    PortFamily,
    PortSpec,
    check_compatibility,
    coerce,
    json_port,
)

# (source, target, compatible, warning, coercion) — the golden table
MATRIX: list[tuple[PortSpec, PortSpec, bool, str | None, str | None]] = [
    (MESSAGE, MESSAGE, True, None, None),
    (TEXT, TEXT, True, None, None),
    (ANY, MESSAGE, True, "W201", None),
    (MESSAGE, ANY, True, "W201", None),
    (MESSAGE, TEXT, True, "W203", "message_to_text"),
    (TEXT, MESSAGE, True, "W203", "text_to_message"),
    (DOCUMENTS, TEXT, True, "W203", "documents_to_text"),
    (JSON, TEXT, True, "W203", "json_to_text"),
    (TEXT, JSON, True, "W203", "text_to_json"),  # parse text/message as JSON (structured output)
    (TEXT, DOCUMENTS, False, None, None),
    (MESSAGE, TOOLSET, False, None, None),
    (ROUTE, TEXT, False, None, None),
    (MESSAGE, MESSAGES, True, "W202", "wrap_list"),  # auto list-wrap
    (MESSAGES, MESSAGE, False, None, None),  # list → scalar never implicit
]


@pytest.mark.parametrize(("source", "target", "ok", "warning", "coercion"), MATRIX)
def test_compatibility_matrix(
    source: PortSpec,
    target: PortSpec,
    ok: bool,
    warning: str | None,
    coercion: str | None,
) -> None:
    result = check_compatibility(source, target)
    assert result.compatible == ok, result.reason
    if warning:
        assert result.warning == warning
    if coercion:
        assert result.coercion == coercion


def test_structural_subset_json_ports() -> None:
    ticket = json_port(
        {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        ref="myco:Ticket",
    )
    loose = json_port({"type": "object"}, ref="myco:Loose")
    assert check_compatibility(ticket, loose).compatible  # anything → loose target
    # loose source does not satisfy a target requiring `id`
    assert not check_compatibility(loose, ticket).compatible


def test_structural_check_is_directional() -> None:
    a = json_port(
        {
            "type": "object",
            "properties": {"id": {"type": "string"}, "extra": {"type": "string"}},
            "required": ["id"],
        },
        ref="myco:Rich",
    )
    b = json_port(
        {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        ref="myco:Slim",
    )
    assert check_compatibility(a, b).compatible


def test_coercion_functions() -> None:
    assert coerce.apply("message_to_text", Message(role="user", content="hi")) == "hi"
    message = coerce.apply("text_to_message", "yo")
    assert isinstance(message, Message)
    assert message.role == "user"
    assert coerce.apply("wrap_list", "x") == ["x"]
    assert coerce.apply("message_to_text+wrap_list", Message(content="a")) == ["a"]


def test_port_spec_frozen() -> None:
    with pytest.raises((TypeError, Exception)):
        MESSAGE.is_list = True  # type: ignore[misc]


def test_families_complete() -> None:
    assert {f.value for f in PortFamily} == {
        "MESSAGE",
        "DATA",
        "TABLE",
        "DOCUMENTS",
        "EMBEDDING",
        "MODEL",
        "VECTORSTORE",
        "TOOLSET",
        "ROUTE",
        "FILE",
        "ANY",
    }


def test_custom_port_cross_family_incompatible() -> None:
    custom = PortSpec(schema_ref="x:Y", json_schema={"type": "object"}, family=PortFamily.EMBEDDING)
    assert not check_compatibility(custom, JSON).compatible


def test_compatibility_results_are_cached() -> None:
    """SPEC §4.3 'cache results': repeated checks return the cached Compat."""
    a = PortSpec(schema_ref="x:CacheA", json_schema={"type": "string"}, family=PortFamily.DATA)
    b = PortSpec(schema_ref="x:CacheB", json_schema={"type": "string"}, family=PortFamily.DATA)
    first = check_compatibility(a, b)
    assert check_compatibility(a, b) is first  # same cached object
    # equal specs from different instances hit the same cache entry
    a2 = PortSpec(schema_ref="x:CacheA", json_schema={"type": "string"}, family=PortFamily.DATA)
    assert check_compatibility(a2, b) is first


def test_port_fingerprint_ignores_display_name_but_not_shape() -> None:
    plain = PortSpec(schema_ref="x:F", json_schema={"type": "string"}, family=PortFamily.DATA)
    named = PortSpec(
        schema_ref="x:F",
        json_schema={"type": "string"},
        family=PortFamily.DATA,
        display_name="Fancy",
    )
    listed = PortSpec(
        schema_ref="x:F", json_schema={"type": "string"}, family=PortFamily.DATA, is_list=True
    )
    assert plain.fingerprint == named.fingerprint
    assert plain.fingerprint != listed.fingerprint
