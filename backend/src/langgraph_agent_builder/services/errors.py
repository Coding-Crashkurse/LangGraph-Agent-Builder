"""Domain errors raised by the service layer (REFACTOR.md §5).

Routes stay parse-call-serialize: services raise these instead of returning
sentinel values for business-rule violations, and app-level exception handlers
(`langgraph_agent_builder.app`) translate them to HTTP statuses (404 / 409 / 422). They extend the
`langgraph_agent_builder.errors` hierarchy so ``except LabError`` still catches everything the
domain raises on purpose.
"""

from __future__ import annotations

from langgraph_agent_builder.errors import LabRuntimeError


class NotFoundError(LabRuntimeError):
    """A referenced entity does not exist — HTTP 404."""


class ConflictError(LabRuntimeError):
    """The operation conflicts with current state — HTTP 409."""


class SlugConflictError(ConflictError):
    """A flow slug is already taken (also raised on unique-constraint races)."""


class FlowLockedError(ConflictError):
    """The flow is locked; edits are refused until it is unlocked (SPEC §9.1)."""


__all__ = ["ConflictError", "FlowLockedError", "NotFoundError", "SlugConflictError"]
