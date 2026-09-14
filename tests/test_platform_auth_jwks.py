"""JWKS (kid-selected) verification + key rotation (HARDENING-PLAN A1).

`decode_platform_token` can resolve the RS256 signing key from a JWKS URL by the
token's `kid` instead of a static `JWT_PUBLIC_KEY`. This supports zero-downtime
rotation: publish a new key (new kid), both verify while old tokens live, then
retire the old kid. Uses an in-memory fake JWK client (no HTTP).
"""

from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from jwt.algorithms import RSAAlgorithm

import smart_llm.platform_auth as pa


def _keypair() -> tuple[str, str]:
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = k.private_bytes(
        ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()
    ).decode()
    pub = (
        k.public_key()
        .public_bytes(ser.Encoding.PEM, ser.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return priv, pub


def _jwk(pub: str, kid: str) -> dict:
    """Build a JWK the same way the user-master JWKS endpoint does."""
    obj = load_pem_public_key(pub.encode())
    j = json.loads(RSAAlgorithm.to_jwk(obj))
    j.update({"use": "sig", "alg": "RS256", "kid": kid})
    return j


class _FakeJWKClient:
    """In-memory stand-in for PyJWKClient — selects a key by the token's kid."""

    def __init__(self, jwks: dict):
        self._by_kid = {k["kid"]: jwt.PyJWK.from_dict(k) for k in jwks["keys"]}

    def get_signing_key_from_jwt(self, token: str):
        kid = jwt.get_unverified_header(token).get("kid")
        if kid not in self._by_kid:
            raise jwt.PyJWKClientError(f"no matching kid {kid!r}")
        return self._by_kid[kid]


def _tok(priv: str, kid: str) -> str:
    return jwt.encode(
        {"sub": "u1", "exp": int(time.time()) + 3600},
        priv,
        algorithm="RS256",
        headers={"kid": kid},
    )


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for v in ("JWT_PUBLIC_KEY", "JWT_AUDIENCE", "JWT_ISSUER", "JWT_JWKS_URL"):
        monkeypatch.delenv(v, raising=False)
    pa._jwks_clients.clear()
    yield
    pa._jwks_clients.clear()


def test_jwks_kid_selection_and_rotation(monkeypatch):
    privA, pubA = _keypair()
    privB, pubB = _keypair()
    url = "https://user-master/.well-known/jwks.json"
    pa._jwks_clients[url] = _FakeJWKClient(
        {"keys": [_jwk(pubA, "kA"), _jwk(pubB, "kB")]}
    )
    monkeypatch.setenv("JWT_JWKS_URL", url)
    # During rotation both keys are published → tokens under either kid verify.
    assert pa.decode_platform_token(_tok(privA, "kA"), "")["sub"] == "u1"
    assert pa.decode_platform_token(_tok(privB, "kB"), "")["sub"] == "u1"
    assert pa.platform_auth_configured() is True


def test_unknown_kid_rejected(monkeypatch):
    privA, pubA = _keypair()
    url = "https://user-master/jwks"
    pa._jwks_clients[url] = _FakeJWKClient({"keys": [_jwk(pubA, "kA")]})
    monkeypatch.setenv("JWT_JWKS_URL", url)
    with pytest.raises(jwt.InvalidTokenError):
        pa.decode_platform_token(_tok(privA, "kZ"), "")  # kid not in the set


def test_forged_key_for_known_kid_rejected(monkeypatch):
    # Token signed with a DIFFERENT private key but claiming a published kid →
    # signature verification against that kid's public key must fail.
    privA, pubA = _keypair()
    privEvil, _ = _keypair()
    url = "https://user-master/jwks"
    pa._jwks_clients[url] = _FakeJWKClient({"keys": [_jwk(pubA, "kA")]})
    monkeypatch.setenv("JWT_JWKS_URL", url)
    with pytest.raises(jwt.InvalidTokenError):
        pa.decode_platform_token(_tok(privEvil, "kA"), "")


def test_static_public_key_still_works_without_jwks(monkeypatch):
    # No JWT_JWKS_URL → falls back to the static public key path.
    priv, pub = _keypair()
    monkeypatch.setenv("JWT_PUBLIC_KEY", pub)
    assert pa.decode_platform_token(_tok(priv, "kA"), "")["sub"] == "u1"
