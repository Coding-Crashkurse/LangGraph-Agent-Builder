"""Client-scope contextvar for public-agent session namespacing (SPEC §7.11)."""

from __future__ import annotations

import hashlib
from contextvars import ContextVar

current_client_scope: ContextVar[str] = ContextVar("lga_a2a_client_scope", default="")


def scope_for_api_key(key: str) -> str:
    return "key:" + hashlib.sha256(key.encode()).hexdigest()[:16]


def scope_for_ip(ip: str) -> str:
    return "ip:" + hashlib.sha256(ip.encode()).hexdigest()[:16]
