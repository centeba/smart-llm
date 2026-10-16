"""Shared platform JWT verification for SentinelBuild services.

user-master is the only signer and every token is RS256 (roadmap 2.3). The
public key (``JWT_JWKS_URL``, or a static ``JWT_PUBLIC_KEY``) and the expected
``aud``/``iss`` (``JWT_AUDIENCE`` / ``JWT_ISSUER``) are read from the
environment, so no per-service config schema changes are needed — the same
variables are set uniformly across every deployment (see
docs/deploy-to-railway.md, Phase 7).

Only RS256 is accepted: there is no shared HMAC secret to forge with, and
``alg=none`` / HS256 are rejected, so there is no algorithm-confusion
downgrade. ``aud``/``iss`` are enforced when configured.
"""

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


#: Scopes a verified token may carry by default. user-master mints ``full``
#: access tokens, short-lived ``pre_2fa`` tokens (only valid for completing
#: 2FA) and long-lived ``refresh`` tokens — the latter two must never be
#: accepted as a bearer credential by any service.
DEFAULT_ALLOWED_SCOPES: tuple[str, ...] = ("full",)


def decode_platform_token(
    token: str,
    *,
    require: list[str] | None = None,
    allowed_scopes: tuple[str, ...] | None = DEFAULT_ALLOWED_SCOPES,
) -> dict[str, Any]:
    """Verify a SentinelBuild platform JWT: RS256, user-master's public key.

    ``require`` is an optional list of claims that must be present (e.g.
    ``["sub", "exp"]``).

    ``allowed_scopes`` is the set of ``scope`` claims accepted; it defaults to
    ``("full",)`` so a ``refresh`` or ``pre_2fa`` token (same signing key, but
    not a bearer credential) is rejected everywhere by default. A token with
    no ``scope`` claim is rejected too. Pass the specific scope a flow needs
    (e.g. ``("pre_2fa",)`` for the 2FA-completion endpoint) or ``None`` to
    skip the check. Raises ``jwt.InvalidTokenError`` (or a subclass) on any
    failure.
    """
    public_key = os.environ.get("JWT_PUBLIC_KEY", "")
    jwks_url = os.environ.get("JWT_JWKS_URL", "")
    audience = os.environ.get("JWT_AUDIENCE", "")
    issuer = os.environ.get("JWT_ISSUER", "")

    alg = jwt.get_unverified_header(token).get("alg")  # parses header, no verify
    if alg != "RS256":
        raise jwt.InvalidAlgorithmError(f"Unsupported JWT alg: {alg!r}")
    # Prefer JWKS (kid-selected, supports rotation); fall back to a static key.
    if jwks_url:
        key = _jwks_signing_key(token, jwks_url)
    elif public_key:
        key = _normalize_pem(public_key)
    else:
        raise jwt.InvalidTokenError("neither JWT_JWKS_URL nor JWT_PUBLIC_KEY is set")
    algorithms = ["RS256"]

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
    payload: dict[str, Any] = jwt.decode(
        token, key, algorithms=algorithms, options=cast(Any, options), **kwargs
    )
    if allowed_scopes is not None and payload.get("scope") not in allowed_scopes:
        raise jwt.InvalidTokenError(
            f"Token scope {payload.get('scope')!r} is not accepted here"
        )
    return payload


def platform_auth_configured() -> bool:
    """True if an RS256 verification key is available (a JWKS URL or a static
    public key). Used by fail-closed guards: refuse rather than accept when
    there is nothing to verify with."""
    return bool(os.environ.get("JWT_PUBLIC_KEY") or os.environ.get("JWT_JWKS_URL"))
