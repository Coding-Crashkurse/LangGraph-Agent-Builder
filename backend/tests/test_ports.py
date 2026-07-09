"""Port compatibility matrix (golden table) + coercions (SPEC §15.1)."""

from __future__ import annotations

import pytest

from lga.sdk.ports import (
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
    (TEXT, JSON, False, None, None),  # no registered coercion — Type Convert required
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
