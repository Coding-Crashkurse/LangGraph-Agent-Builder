"""Secret scrubbing for events & logs (SPEC §10.5).

Two mechanisms, exactly as the spec mandates:

* a **regex scrubber** for common credential shapes (catches a leaked key even
  when we never saw its value), and
* a **known-value scrubber** fed the exact resolved secret values — the compiler
  calls :func:`register_secret` whenever it resolves a ``$secret`` ref, so the
  actual plaintext is redacted wherever it later surfaces.

Both redact to ``***``. Everything here is pure, dependency-free and idempotent,
so it is safe to apply on the event bus, in the executor's emit funnel, and as a
logging filter without worrying about double application or import layering.
"""

from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "***"

# Conservative, low-false-positive shapes for provider credentials/tokens.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),  # Anthropic
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),  # bearer auth headers
    re.compile(r"lga_sk_[A-Za-z0-9]{16,}"),  # our own API keys
)

# Exact resolved secret values, registered by the compiler at resolve time.
_KNOWN: set[str] = set()
_MIN_KNOWN_LEN = 6  # never redact trivially short "secrets" (avoids nuking normal text)


def register_secret(value: str | None) -> None:
    """Record a resolved secret value so it can be scrubbed from events/logs."""
    if value and len(value) >= _MIN_KNOWN_LEN:
        _KNOWN.add(str(value))


def scrub_text(text: str) -> str:
    """Redact known secret values and credential-shaped tokens from a string."""
    for value in _KNOWN:
        if value in text:
            text = text.replace(value, REDACTED)
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scrub_data(value: Any) -> Any:
    """Recursively scrub strings inside dicts/lists/tuples; other types pass through."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: scrub_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(scrub_data(v) for v in value)
    return value


class SecretScrubFilter(logging.Filter):
    """Logging filter that scrubs secrets from the final log message (SPEC §10.5).

    Attached to the root handlers so every emitted line is redacted; collapses
    lazy ``%`` args into the already-scrubbed message.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # never let scrubbing break logging
            return True
        scrubbed = scrub_text(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


def install_log_scrubbing(logger: logging.Logger | None = None) -> None:
    """Idempotently attach :class:`SecretScrubFilter` to a logger's handlers."""
    root = logger or logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, SecretScrubFilter) for f in handler.filters):
            handler.addFilter(SecretScrubFilter())
