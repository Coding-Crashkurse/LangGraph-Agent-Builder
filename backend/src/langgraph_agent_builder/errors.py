"""Domain error hierarchy (REFACTOR.md §5).

Every error the ``lab`` domain raises *on purpose* derives from `LabError`, so a
caller can ``except LabError`` to catch any expected domain failure while a
genuine programming bug (an ``AttributeError``, ``KeyError``, …) still
propagates untouched.

Re-rooting is deliberately *additive*: the category bases mix `LabError` with
the builtin the call sites and tests already rely on (`ValueError` for invalid
input, `RuntimeError` for an illegal operation/state), so existing
``except ValueError`` / ``except RuntimeError`` handlers and ``isinstance``
checks keep working unchanged — the exceptions simply also become `LabError`.

Adapters (LLM providers, vector backends, A2A/MCP transports) translate vendor
exceptions into these domain errors at the boundary so the core never has to
know a vendor SDK's exception types (REFACTOR.md §3, §5).
"""

from __future__ import annotations


class LabError(Exception):
    """Root of every error the lab domain raises deliberately."""


class LabValueError(LabError, ValueError):
    """Invalid input/value at a domain boundary — also a builtin ``ValueError``."""


class LabRuntimeError(LabError, RuntimeError):
    """Illegal operation or state at runtime — also a builtin ``RuntimeError``."""


__all__ = ["LabError", "LabRuntimeError", "LabValueError"]
