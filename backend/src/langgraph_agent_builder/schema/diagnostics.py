"""Diagnostic model + normative code catalog (SPEC §5.4, §5.6, §7.4, §8.1)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from langgraph_agent_builder.errors import LabError


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DiagnosticCode(StrEnum):
    # schema / structure
    E001 = "E001"  # FlowSpec schema invalid / unknown schema_version
    E002 = "E002"  # Unknown component_id
    E003 = "E003"  # Duplicate node id / reserved id misuse
    # config
    E010 = "E010"  # Required field empty (and not tweakable-at-run)
    E011 = "E011"  # Field value fails JSON schema
    E012 = "E012"  # $secret/$var reference does not exist
    E013 = "E013"  # Vector store connection referenced by node does not exist
    E014 = "E014"  # Credential ($secret) assigned to a non-credential (non-Secret) field
    E015 = "E015"  # ComponentBuildFailed — build() raised while emitting the graph
    # edges
    E020 = "E020"  # Edge type-incompatible
    E021 = "E021"  # Tool edge into non-Tools port / from non-Toolset output
    E022 = "E022"  # Router branch label not covered / duplicate branch target label
    E023 = "E023"  # Router output wired as data
    E024 = "E024"  # Edge into start / out of terminal node
    # graph
    E030 = "E030"  # No start / no terminal / not connected from start
    E031 = "E031"  # Required input port unconnected
    E032 = "E032"  # Cycle contains no ROUTER or INTERRUPT node
    E040 = "E040"  # Interrupt node in a parallel branch set
    # publish guards
    E060 = "E060"  # MissingA2ADescription
    E061 = "E061"  # SkillExamplesRecommended (warning severity)
    E062 = "E062"  # MissingMCPDescription
    E063 = "E063"  # Interrupt nodes exposed over MCP without auto_resolve policy
    E064 = "E064"  # Structured result served over MCP/A2A without declared output_schema (warning)
    E065 = "E065"  # end.output_schema is not a valid JSON Schema
    # deep validate / runtime preflight
    E901 = "E901"  # BackendExtraMissing (vendor client extra not installed)
    E902 = "E902"  # VectorStoreUnreachable (health_check failed)
    E903 = "E903"  # CollectionMissing
    E904 = "E904"  # EmbeddingDimensionMismatch (collection dim ≠ embedding dim)
    E905 = "E905"  # McpServerUnreachable
    E906 = "E906"  # ModelProviderAuthFailed
    # warnings
    W201 = "W201"  # ANY-typed edge
    W202 = "W202"  # Auto list-wrap coercion inserted
    W203 = "W203"  # Implicit coercion inserted
    W204 = "W204"  # BackendSpecificFilter (raw_filter passthrough)
    W301 = "W301"  # Deprecated field/output in use
    W302 = "W302"  # Component version migrated
    W303 = "W303"  # Unknown config key (not a declared field; ignored at build)
    W401 = "W401"  # Node unreachable from start
    W402 = "W402"  # Embedding port unwired — runtime falls back to fake embeddings
    # info
    I501 = "I501"  # Cycle detected — recursion_limit applies


SEVERITY_OVERRIDES: dict[DiagnosticCode, Severity] = {
    DiagnosticCode.E061: Severity.WARNING,
    DiagnosticCode.E064: Severity.WARNING,
}


def severity_for(code: DiagnosticCode) -> Severity:
    if code in SEVERITY_OVERRIDES:
        return SEVERITY_OVERRIDES[code]
    if code.value.startswith("E"):
        return Severity.ERROR
    if code.value.startswith("W"):
        return Severity.WARNING
    return Severity.INFO


class Diagnostic(BaseModel):
    code: DiagnosticCode
    severity: Severity
    node_id: str | None = None
    field: str | None = None
    edge_id: str | None = None
    message: str
    fix_hint: str | None = None

    @classmethod
    def make(
        cls,
        code: DiagnosticCode,
        message: str,
        *,
        node_id: str | None = None,
        field: str | None = None,
        edge_id: str | None = None,
        fix_hint: str | None = None,
    ) -> Diagnostic:
        return cls(
            code=code,
            severity=severity_for(code),
            node_id=node_id,
            field=field,
            edge_id=edge_id,
            message=message,
            fix_hint=fix_hint,
        )


def has_errors(diagnostics: list[Diagnostic]) -> bool:
    return any(d.severity == Severity.ERROR for d in diagnostics)


# Runtime error codes (SPEC §5.6) — carried on run rows and RT events.
class RuntimeErrorCode(StrEnum):
    RT101 = "RT101"  # DataWriteConflict
    RT102 = "RT102"  # RouterInvalidLabel
    RT103 = "RT103"  # NodeException (wrapped)
    RT104 = "RT104"  # Cancelled
    RT105 = "RT105"  # RecursionLimit
    RT106 = "RT106"  # SecretResolutionFailed
    RT107 = "RT107"  # VectorStoreError(backend, detail)


class RuntimeError_(LabError):
    """Runtime error with a normative RT code and node attribution."""

    def __init__(self, code: RuntimeErrorCode, message: str, node_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.node_id = node_id
