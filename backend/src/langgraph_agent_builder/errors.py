"""Domain errors translated to HTTP responses by the app-level handlers."""

from __future__ import annotations

from agentplane_core import ValidationIssue


class NotFoundError(Exception):
    """Requested entity does not exist."""


class ConflictError(Exception):
    """Write conflicts with existing state (e.g. duplicate flow name)."""


class InvalidDefinitionError(Exception):
    """A definition failed to parse; carries structured issues when available."""

    def __init__(self, message: str, issues: list[ValidationIssue] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


class RuntimeUnavailableError(Exception):
    """The agentplane runtime is not configured or not reachable."""


class RuntimeRejectedError(Exception):
    """The runtime rejected an operation with validation issues (authoritative)."""

    def __init__(self, message: str, issues: list[ValidationIssue]) -> None:
        super().__init__(message)
        self.issues = issues
