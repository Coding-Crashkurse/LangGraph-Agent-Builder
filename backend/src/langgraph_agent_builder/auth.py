"""Request authentication (SPEC §2.7).

``BUILDER_AUTH_MODE=oidc``: the backend validates JWTs from the shared
Keycloak realm (issuer discovery + JWKS, cached) and forwards the caller's
token to runtime calls. ``none`` (default for local dev): requests pass with
the anonymous principal; an optional static ``BUILDER_RUNTIME_TOKEN`` is
forwarded instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from langgraph_agent_builder.services.settings import Settings


@dataclass(frozen=True)
class Principal:
    sub: str
    token: str | None  # bearer forwarded to the runtime (user token or static)


class AuthenticationError(Exception):
    """Missing or invalid credentials (→ 401)."""


class OidcVerifier:
    """Validates RS256 JWTs against the issuer's JWKS (discovered, cached)."""

    def __init__(self, issuer: str, audience: str, *, cache_ttl_s: float = 3600.0) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._cache_ttl_s = cache_ttl_s
        self._keys: dict[str, Any] = {}  # kid -> parsed public key (jwt.PyJWK.key)
        self._fetched_at = 0.0

    async def _jwks(self, *, force: bool = False) -> dict[str, Any]:
        if not force and self._keys and time.monotonic() - self._fetched_at < self._cache_ttl_s:
            return self._keys
        async with httpx.AsyncClient(timeout=10.0) as client:
            discovery = await client.get(f"{self._issuer}/.well-known/openid-configuration")
            discovery.raise_for_status()
            jwks_uri = discovery.json().get("jwks_uri")
            if not isinstance(jwks_uri, str):
                raise AuthenticationError("issuer discovery returned no jwks_uri")
            jwks = await client.get(jwks_uri)
            jwks.raise_for_status()
        keys: dict[str, Any] = {}
        for entry in jwks.json().get("keys", []):
            kid = entry.get("kid")
            # Keycloak publishes an encryption key (use=enc, e.g. RSA-OAEP)
            # alongside the signing key; only signing keys can build a verifier.
            if not isinstance(kid, str) or entry.get("use") == "enc":
                continue
            try:
                keys[kid] = jwt.PyJWK(entry).key
            except jwt.PyJWKError:
                continue
        self._keys = keys
        self._fetched_at = time.monotonic()
        return keys

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            header_kid = jwt.get_unverified_header(token).get("kid")
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError(f"invalid token: {exc}") from exc
        if not isinstance(header_kid, str):
            raise AuthenticationError("token header has no kid")
        kid = header_kid
        keys = await self._jwks()
        if kid not in keys:
            keys = await self._jwks(force=True)  # key rotation
        key = keys.get(kid)
        if key is None:
            raise AuthenticationError("token signed with unknown key")
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience or None,
                options={"verify_aud": bool(self._audience)},
            )
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError(f"invalid token: {exc}") from exc
        return claims


class Authenticator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._verifier = (
            OidcVerifier(settings.oidc_issuer, settings.oidc_audience)
            if settings.auth_mode == "oidc"
            else None
        )

    async def authenticate(self, authorization: str | None) -> Principal:
        if self._verifier is None:
            return Principal(sub="anonymous", token=self._settings.runtime_token or None)
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthenticationError("missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        try:
            claims = await self._verifier.verify(token)
        except httpx.HTTPError as exc:
            raise AuthenticationError(f"issuer unreachable: {exc}") from exc
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise AuthenticationError("token has no sub claim")
        return Principal(sub=sub, token=token)
