"""Domain error hierarchy (REFACTOR.md §5).

Every error the ``lga`` domain raises *on purpose* derives from `LgaError`, so a
caller can ``except LgaError`` to catch any expected domain failure while a
genuine programming bug (an ``AttributeError``, ``KeyError``, …) still
propagates untouched.

Re-rooting is deliberately *additive*: the category bases mix `LgaError` with
the builtin the call sites and tests already rely on (`ValueError` for invalid
input, `RuntimeError` for an illegal operation/state), so existing
``except ValueError`` / ``except RuntimeError`` handlers and ``isinstance``
checks keep working unchanged — the exceptions simply also become `LgaError`.

Adapters (LLM providers, vector backends, A2A/MCP transports) translate vendor
exceptions into these domain errors at the boundary so the core never has to
know a vendor SDK's exception types (REFACTOR.md §3, §5).
"""

from __future__ import annotations


class LgaError(Exception):
    """Root of every error the lga domain raises deliberately."""


class LgaValueError(LgaError, ValueError):
    """Invalid input/value at a domain boundary — also a builtin ``ValueError``."""


class LgaRuntimeError(LgaError, RuntimeError):
    """Illegal operation or state at runtime — also a builtin ``RuntimeError``."""


__all__ = ["LgaError", "LgaRuntimeError", "LgaValueError"]
