"""Dual-mode HS256/RS256 verification for smart_llm.platform_auth.

The shared verifier every service uses. Mirrors the SDK's RS256 contract:
legacy HS256 keeps working, RS256 verifies with JWT_PUBLIC_KEY, aud/iss are
enforced only when configured, and the alg-confusion downgrade (HS256 forged
with the RS256 public key as the HMAC secret) is rejected.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric import rsa

from smart_llm.platform_auth import decode_platform_token, platform_auth_configured

HS = "a-real-32byte-plus-shared-secret-value!!"
AUD, ISS = "sentinelbuild", "user-master"


@pytest.fixture(scope="module")
def keys() -> tuple[str, str]:
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


def _claims(**extra) -> dict:
    return {"sub": "u1", "exp": int(time.time()) + 3600, **extra}


def _forge_hs256_with(secret: str, claims: dict) -> str:
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")  # noqa: E731
    seg = (
        b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        + b"."
        + b64(json.dumps(claims).encode())
    )
    sig = b64(hmac.new(secret.encode(), seg, hashlib.sha256).digest())
    return (seg + b"." + sig).decode()


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for v in ("JWT_PUBLIC_KEY", "JWT_AUDIENCE", "JWT_ISSUER"):
        monkeypatch.delenv(v, raising=False)


def test_legacy_hs256_no_rs_configured(monkeypatch):
    # No JWT_PUBLIC_KEY / aud / iss set -> behaves exactly like today.
    tok = jwt.encode(_claims(), HS, algorithm="HS256")
    assert decode_platform_token(tok, HS)["sub"] == "u1"
    assert platform_auth_configured() is False


def test_rs256_verified_with_public_key(keys, monkeypatch):
    priv, pub = keys
    monkeypatch.setenv("JWT_PUBLIC_KEY", pub)
    monkeypatch.setenv("JWT_AUDIENCE", AUD)
    monkeypatch.setenv("JWT_ISSUER", ISS)
    tok = jwt.encode(_claims(aud=AUD, iss=ISS), priv, algorithm="RS256")
    assert decode_platform_token(tok, HS)["sub"] == "u1"
    assert platform_auth_configured() is True


def test_rs256_wrong_aud_rejected(keys, monkeypatch):
    priv, pub = keys
    monkeypatch.setenv("JWT_PUBLIC_KEY", pub)
    monkeypatch.setenv("JWT_AUDIENCE", AUD)
    tok = jwt.encode(_claims(aud="evil"), priv, algorithm="RS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(tok, HS)


def test_dual_window_both_accepted(keys, monkeypatch):
    priv, pub = keys
    monkeypatch.setenv("JWT_PUBLIC_KEY", pub)  # aud/iss not yet enforced
    assert (
        decode_platform_token(jwt.encode(_claims(), HS, algorithm="HS256"), HS)["sub"]
        == "u1"
    )
    assert (
        decode_platform_token(jwt.encode(_claims(), priv, algorithm="RS256"), HS)["sub"]
        == "u1"
    )


def test_alg_confusion_forgery_rejected(keys, monkeypatch):
    _, pub = keys
    monkeypatch.setenv("JWT_PUBLIC_KEY", pub)
    forged = _forge_hs256_with(pub, _claims())  # HS256 signed with the public key
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(forged, HS)


def test_alg_none_rejected(keys, monkeypatch):
    _, pub = keys
    monkeypatch.setenv("JWT_PUBLIC_KEY", pub)
    tok = jwt.encode(_claims(), key=None, algorithm="none")
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(tok, HS)


def test_require_claims_enforced(monkeypatch):
    # A token missing `exp` is rejected when require=["sub","exp"].
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")  # noqa: E731
    seg = (
        b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        + b"."
        + b64(json.dumps({"sub": "u1"}).encode())
    )
    sig = b64(hmac.new(HS.encode(), seg, hashlib.sha256).digest())
    tok = (seg + b"." + sig).decode()
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_platform_token(tok, HS, require=["sub", "exp"])


def test_rs256_without_public_key_rejected(keys):
    priv, _ = keys  # JWT_PUBLIC_KEY not set (cleared by fixture)
    tok = jwt.encode(_claims(), priv, algorithm="RS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(tok, HS)


def test_final_state_hs_disabled(keys, monkeypatch):
    priv, pub = keys
    monkeypatch.setenv("JWT_PUBLIC_KEY", pub)
    rs = jwt.encode(_claims(), priv, algorithm="RS256")
    hs = jwt.encode(_claims(), HS, algorithm="HS256")
    assert decode_platform_token(rs, "")["sub"] == "u1"  # HS secret unset
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(hs, "")
