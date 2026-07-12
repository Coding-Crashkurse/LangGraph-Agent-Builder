"""Auth: none-mode passes anonymously; oidc-mode validates JWTs and forwards them."""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient, Response

from tests.conftest import RUNTIME_URL, ClientFactory, definition

ISSUER = "http://keycloak.test/realms/agentplane"
AUDIENCE = "builder"
KID = "test-key-1"


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key: rsa.RSAPrivateKey) -> dict[str, str]:
    from jwt.algorithms import RSAAlgorithm

    public_jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {**public_jwk, "kid": KID, "use": "sig", "alg": "RS256"}


def _mock_oidc(key: rsa.RSAPrivateKey) -> None:
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=Response(200, json={"jwks_uri": f"{ISSUER}/jwks"})
    )
    respx.get(f"{ISSUER}/jwks").mock(return_value=Response(200, json={"keys": [_jwk(key)]}))


def _token(key: rsa.RSAPrivateKey, **claims: object) -> str:
    payload: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": f"user-{uuid.uuid4()}",
        "exp": int(time.time()) + 300,
        **claims,
    }
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return jwt.encode(payload, pem, algorithm="RS256", headers={"kid": KID})


async def test_none_mode_is_open(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/flows")).status_code == 200


@respx.mock
async def test_oidc_requires_bearer(make_client: ClientFactory, rsa_key: rsa.RSAPrivateKey) -> None:
    _mock_oidc(rsa_key)
    async with make_client(auth_mode="oidc", oidc_issuer=ISSUER, oidc_audience=AUDIENCE) as client:
        assert (await client.get("/api/v1/flows")).status_code == 401
        bad = await client.get("/api/v1/flows", headers={"Authorization": "Bearer not-a-token"})
        assert bad.status_code == 401


@respx.mock
async def test_oidc_accepts_valid_token(
    make_client: ClientFactory, rsa_key: rsa.RSAPrivateKey
) -> None:
    _mock_oidc(rsa_key)
    token = _token(rsa_key, sub="alice")
    async with make_client(auth_mode="oidc", oidc_issuer=ISSUER, oidc_audience=AUDIENCE) as client:
        resp = await client.get("/api/v1/flows", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


@respx.mock
async def test_oidc_rejects_wrong_audience(
    make_client: ClientFactory, rsa_key: rsa.RSAPrivateKey
) -> None:
    _mock_oidc(rsa_key)
    token = _token(rsa_key, aud="other-app")
    async with make_client(auth_mode="oidc", oidc_issuer=ISSUER, oidc_audience=AUDIENCE) as client:
        resp = await client.get("/api/v1/flows", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


@respx.mock
async def test_oidc_isolates_owners(make_client: ClientFactory, rsa_key: rsa.RSAPrivateKey) -> None:
    _mock_oidc(rsa_key)
    alice = {"Authorization": f"Bearer {_token(rsa_key, sub='alice')}"}
    bob = {"Authorization": f"Bearer {_token(rsa_key, sub='bob')}"}
    async with make_client(auth_mode="oidc", oidc_issuer=ISSUER, oidc_audience=AUDIENCE) as client:
        created = await client.post("/api/v1/flows", json=definition(), headers=alice)
        assert created.status_code == 201
        assert (await client.get("/api/v1/flows/hello-agent", headers=bob)).status_code == 404


@respx.mock
async def test_oidc_forwards_user_token_to_runtime(
    make_client: ClientFactory, rsa_key: rsa.RSAPrivateKey
) -> None:
    """SPEC §2.7: the backend forwards the *user's* token to runtime calls."""
    _mock_oidc(rsa_key)
    token = _token(rsa_key, sub="alice")
    route = respx.post(f"{RUNTIME_URL}/api/v1/definitions/validate").mock(
        return_value=Response(200, json={"valid": True, "issues": []})
    )
    async with make_client(
        auth_mode="oidc",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        runtime_url=RUNTIME_URL,
    ) as client:
        await client.post(
            "/api/v1/flows/validate",
            json=definition(),
            headers={"Authorization": f"Bearer {token}"},
        )
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {token}"
