"""Shared platform JWT verification for SentinelBuild services.

Single source for the HS256->RS256 migration. A service calls
``decode_platform_token`` with the HS256 shared secret it already holds; the
RS256 public key and the expected ``aud``/``iss`` are read from the environment
(``JWT_PUBLIC_KEY`` / ``JWT_AUDIENCE`` / ``JWT_ISSUER``) so no per-service
config schema changes are needed — the same three variables are set uniformly
across every deployment (see docs/deploy-to-railway.md, Phase 7).

The token's own header ``alg`` selects the key: RS256 verifies against the
public key (asymmetric), HS256 against the shared secret (symmetric). The public
key is **never** used as an HMAC secret and ``alg=none`` is rejected, so there
is no algorithm-confusion downgrade. ``aud``/``iss`` are enforced only when
configured, so pre-migration HS256 tokens (which carry neither) keep validating.
Once every issuer emits RS256, unset the shared secret to disable HS256.
"""

from __future__ import annotations

import os
from typing import Any, cast

import jwt


def _normalize_pem(key: str) -> str:
    """Allow a PEM key supplied with literal ``\\n`` (env/secret stores that
    don't preserve newlines) to be used as real PEM."""
    return key.replace("\\n", "\n") if key and "\\n" in key else key


# JWKS clients are cached per URL — PyJWKClient caches the fetched keys, so only
# a cache-miss (e.g. a newly-rotated kid) triggers a network fetch.
_jwks_clients: dict[str, jwt.PyJWKClient] = {}


def _jwks_signing_key(token: str, jwks_url: str) -> Any:
    """Resolve the RS256 signing key from a JWKS URL by the token's ``kid``.

    Wraps any JWK-resolution failure (including a network/fetch error, which
    PyJWKClient raises as a PyJWTError subclass) as ``InvalidTokenError`` so
    callers' ``except InvalidTokenError`` handles it uniformly.
    """
    client = _jwks_clients.get(jwks_url)
    if client is None:
        client = jwt.PyJWKClient(jwks_url, cache_keys=True)
        _jwks_clients[jwks_url] = client
    try:
        return client.get_signing_key_from_jwt(token).key
    except jwt.PyJWTError as exc:
        raise jwt.InvalidTokenError(f"JWKS key resolution failed: {exc}") from exc


def decode_platform_token(
    token: str,
    hs_secret: str,
    *,
    require: list[str] | None = None,
) -> dict[str, Any]:
    """Verify a SentinelBuild platform JWT in HS256/RS256 dual mode.

    ``hs_secret`` is the caller's existing HS256 shared secret. ``require`` is an
    optional list of claims that must be present (e.g. ``["sub", "exp"]``).
    Raises ``jwt.InvalidTokenError`` (or a subclass) on any failure.
    """
    public_key = os.environ.get("JWT_PUBLIC_KEY", "")
    jwks_url = os.environ.get("JWT_JWKS_URL", "")
    audience = os.environ.get("JWT_AUDIENCE", "")
    issuer = os.environ.get("JWT_ISSUER", "")

    alg = jwt.get_unverified_header(token).get("alg")  # parses header, no verify
    if alg == "RS256":
        # Prefer JWKS (kid-selected, supports rotation); fall back to a static
        # public key. The public key is never used as an HMAC secret.
        if jwks_url:
            key, algorithms = _jwks_signing_key(token, jwks_url), ["RS256"]
        elif public_key:
            key, algorithms = _normalize_pem(public_key), ["RS256"]
        else:
            raise jwt.InvalidTokenError(
                "RS256 token but neither JWT_JWKS_URL nor JWT_PUBLIC_KEY is set"
            )
    elif alg == "HS256":
        if not hs_secret:
            raise jwt.InvalidTokenError("HS256 token but shared secret not set")
        key, algorithms = hs_secret, ["HS256"]
    else:
        raise jwt.InvalidAlgorithmError(f"Unsupported JWT alg: {alg!r}")

    options: dict[str, Any] = {}
    kwargs: dict[str, Any] = {}
    if require:
        options["require"] = require
    if audience:
        kwargs["audience"] = audience
    else:
        options["verify_aud"] = False
    if issuer:
        kwargs["issuer"] = issuer
    return jwt.decode(
        token, key, algorithms=algorithms, options=cast(Any, options), **kwargs
    )


def platform_auth_configured() -> bool:
    """True if an RS256 verification path is available (a static public key or a
    JWKS URL). Used by services' fail-closed guards: reject requests when
    neither that nor an HS secret is set rather than silently accepting."""
    return bool(os.environ.get("JWT_PUBLIC_KEY") or os.environ.get("JWT_JWKS_URL"))
