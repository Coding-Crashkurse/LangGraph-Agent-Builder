"""Unit tests for lga.schema.diagnostics — severity mapping + runtime errors."""

from __future__ import annotations

from lga.errors import LgaError
from lga.schema.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    RuntimeError_,
    RuntimeErrorCode,
    Severity,
    has_errors,
    severity_for,
)


def test_severity_for_error_prefix() -> None:
    assert severity_for(DiagnosticCode.E001) == Severity.ERROR


def test_severity_for_warning_prefix() -> None:
    assert severity_for(DiagnosticCode.W201) == Severity.WARNING


def test_severity_for_info_prefix() -> None:
    assert severity_for(DiagnosticCode.I501) == Severity.INFO


def test_severity_override_downgrades_e061_to_warning() -> None:
    # E061 has an E-prefix but is overridden to WARNING severity.
    assert severity_for(DiagnosticCode.E061) == Severity.WARNING


def test_diagnostic_make_assigns_severity_and_fields() -> None:
    diag = Diagnostic.make(
        DiagnosticCode.E010,
        "Required field empty",
        node_id="n1",
        field="prompt",
        fix_hint="set a value",
    )
    assert diag.severity == Severity.ERROR
    assert diag.node_id == "n1"
    assert diag.field == "prompt"
    assert diag.fix_hint == "set a value"


def test_diagnostic_make_warning_severity_for_override_code() -> None:
    diag = Diagnostic.make(DiagnosticCode.E061, "examples recommended")
    assert diag.severity == Severity.WARNING


def test_has_errors_true_when_any_error() -> None:
    diags = [
        Diagnostic.make(DiagnosticCode.W201, "any edge"),
        Diagnostic.make(DiagnosticCode.E020, "type mismatch"),
    ]
    assert has_errors(diags) is True


def test_has_errors_false_for_only_warnings_and_info() -> None:
    diags = [
        Diagnostic.make(DiagnosticCode.W201, "any edge"),
        Diagnostic.make(DiagnosticCode.I501, "cycle"),
    ]
    assert has_errors(diags) is False


def test_has_errors_empty_list() -> None:
    assert has_errors([]) is False


def test_runtime_error_carries_code_and_node() -> None:
    err = RuntimeError_(RuntimeErrorCode.RT103, "node blew up", node_id="n7")
    assert err.code == RuntimeErrorCode.RT103
    assert err.node_id == "n7"
    assert str(err) == "node blew up"


def test_runtime_error_is_lga_error() -> None:
    err = RuntimeError_(RuntimeErrorCode.RT104, "cancelled")
    assert isinstance(err, LgaError)
    assert err.node_id is None
