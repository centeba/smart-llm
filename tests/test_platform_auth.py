"""RS256 verification for smart_llm.platform_auth.

The shared verifier every service uses. user-master is the only signer (roadmap
2.3): tokens verify with JWT_PUBLIC_KEY (or JWT_JWKS_URL, see
test_platform_auth_jwks.py), aud/iss are enforced when configured, and HS256 —
including the alg-confusion forgery with the public key as the HMAC secret —
and alg=none are rejected.
"""

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


def _claims(**extra: object) -> dict[str, object]:
    # Every real platform token carries a scope; ``full`` is the bearer scope.
    return {"sub": "u1", "exp": int(time.time()) + 3600, "scope": "full", **extra}


def _forge_hs256_with(secret: str, claims: dict[str, object]) -> str:
    def b64(b: bytes) -> bytes:
        return base64.urlsafe_b64encode(b).rstrip(b"=")

    seg = (
        b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        + b"."
        + b64(json.dumps(claims).encode())
    )
    sig = b64(hmac.new(secret.encode(), seg, hashlib.sha256).digest())
    return (seg + b"." + sig).decode()


@pytest.fixture(autouse=True)
def _public_key(keys: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_PUBLIC_KEY", keys[1])
    for v in ("JWT_JWKS_URL", "JWT_AUDIENCE", "JWT_ISSUER"):
        monkeypatch.delenv(v, raising=False)


def _rs(priv: str, **claims: object) -> str:
    return jwt.encode(_claims(**claims), priv, algorithm="RS256")


def test_rs256_verified_with_public_key(keys, monkeypatch):
    monkeypatch.setenv("JWT_AUDIENCE", AUD)
    monkeypatch.setenv("JWT_ISSUER", ISS)
    assert decode_platform_token(_rs(keys[0], aud=AUD, iss=ISS))["sub"] == "u1"
    assert platform_auth_configured() is True


def test_rs256_wrong_aud_rejected(keys, monkeypatch):
    monkeypatch.setenv("JWT_AUDIENCE", AUD)
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(_rs(keys[0], aud="evil"))


def test_rs256_missing_iss_rejected_once_enforced(keys, monkeypatch):
    monkeypatch.setenv("JWT_ISSUER", ISS)
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(_rs(keys[0]))


def test_rs256_signed_with_another_key_rejected():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(jwt.encode(_claims(), other, algorithm="RS256"))


def test_hs256_rejected():
    tok = jwt.encode(
        _claims(), "a-real-32byte-plus-shared-secret-value!!", algorithm="HS256"
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(tok)


def test_alg_confusion_forgery_rejected(keys):
    forged = _forge_hs256_with(keys[1], _claims())  # HS256 signed with the public key
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(forged)


def test_alg_none_rejected():
    tok = jwt.encode(_claims(), key=None, algorithm="none")
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(tok)


def test_require_claims_enforced(keys):
    # A token missing `exp` is rejected when require=["sub","exp"].
    tok = jwt.encode({"sub": "u1", "scope": "full"}, keys[0], algorithm="RS256")
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_platform_token(tok, require=["sub", "exp"])


def test_no_key_configured(keys, monkeypatch):
    monkeypatch.delenv("JWT_PUBLIC_KEY")
    assert platform_auth_configured() is False
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(_rs(keys[0]))


# ── scope allowlist ───────────────────────────────────────────────────────────
# user-master also mints ``pre_2fa`` tokens with the access-token key (refresh
# tokens have their own key since 2.2). They must never be accepted as a bearer
# credential.


@pytest.mark.parametrize("scope", ["refresh", "pre_2fa", "anything-else"])
def test_non_bearer_scope_rejected_by_default(keys, scope):
    with pytest.raises(jwt.InvalidTokenError, match="scope"):
        decode_platform_token(_rs(keys[0], scope=scope))


def test_missing_scope_rejected_by_default(keys):
    claims = _claims()
    del claims["scope"]
    with pytest.raises(jwt.InvalidTokenError, match="scope"):
        decode_platform_token(jwt.encode(claims, keys[0], algorithm="RS256"))


def test_full_scope_accepted_by_default(keys):
    assert decode_platform_token(_rs(keys[0]))["scope"] == "full"


def test_flow_can_opt_into_a_specific_scope(keys):
    tok = _rs(keys[0], scope="pre_2fa")
    assert decode_platform_token(tok, allowed_scopes=("pre_2fa",))["scope"] == "pre_2fa"
    # ...but opting into one scope still rejects the others.
    with pytest.raises(jwt.InvalidTokenError):
        decode_platform_token(tok, allowed_scopes=("full",))


def test_allowed_scopes_none_skips_the_check(keys):
    tok = _rs(keys[0], scope="refresh")
    assert decode_platform_token(tok, allowed_scopes=None)["scope"] == "refresh"
