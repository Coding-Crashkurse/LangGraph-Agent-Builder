"""Client-scope contextvar for public-agent session namespacing (SPEC §7.11)."""

from __future__ import annotations

import hashlib
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from a2a.server.context import ServerCallContext

current_client_scope: ContextVar[str] = ContextVar("lga_a2a_client_scope", default="")


def scope_for_api_key(key: str) -> str:
    return "key:" + hashlib.sha256(key.encode()).hexdigest()[:16]


def scope_for_ip(ip: str) -> str:
    return "ip:" + hashlib.sha256(ip.encode()).hexdigest()[:16]


def resolve_client_scope(context: ServerCallContext | None) -> str:
    """`lga_client_scope` from the sdk call-context state, else the auth
    middleware's contextvar — the one resolution used by executor and store."""
    state = getattr(context, "state", None) if context is not None else None
    if state:
        value = state.get("lga_client_scope")
        if value:
            return str(value)
    return current_client_scope.get()
