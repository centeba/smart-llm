"""Shared JWT revocation denylist (HARDENING-PLAN / pre-launch Gate 3).

Platform access tokens are stateless and — until now — only expired, never
revoked. This adds a Redis-backed denylist so a token can be killed before its
``exp``: on logout (one ``jti``) or on a security event like a password change
(every token a user holds, via an ``iat`` cutoff).

The denylist lives in a SHARED, un-prefixed key namespace (``sb:revoked:*``) on
the common Redis instance so every service that verifies a platform JWT can
consult the same list — user-master writes it; each service's auth dependency
reads it via :func:`is_revoked` right after `decode_platform_token`.

Entries always carry a TTL bounded by the token's own remaining lifetime, so the
denylist can never grow past the longest-lived outstanding token.

Fail-open on a Redis outage (returns "not revoked" + logs): revocation is a
best-effort second layer on top of the token's ``exp``; a Redis blip must not
lock every user out. The short token TTL is the backstop.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_JTI_PREFIX = "sb:revoked:jti:"
_USER_PREFIX = "sb:revoked:user:"

# ── Cross-service adoption helper ─────────────────────────────────────────────
# user-master writes the denylist; every OTHER service checks it via
# ``token_is_revoked`` in its auth dependency. The denylist lives in ONE shared
# namespace, so a consumer must read the SAME Redis logical DB user-master
# writes (DB 0), which may differ from the service's own Redis DB (e.g. pages-api
# uses DB 4). Point ``TOKEN_REVOCATION_REDIS_URL`` at that shared DB per service.
# Unset → the check is a no-op (revocation not enforced here; the short token
# TTL is the backstop), so adoption is opt-in and can't break a service.
_rev_redis: Any = None
_rev_redis_init = False


def _revocation_redis() -> Any:
    global _rev_redis, _rev_redis_init
    if not _rev_redis_init:
        url = os.environ.get("TOKEN_REVOCATION_REDIS_URL")
        if url:
            try:
                from redis.asyncio import from_url

                _rev_redis = from_url(url, decode_responses=True)
            except Exception:  # noqa: BLE001 — never let wiring break auth
                logger.warning("token_revocation_redis_init_failed", exc_info=True)
                _rev_redis = None
        _rev_redis_init = True
    return _rev_redis


def _revocation_strict() -> bool:
    """When ``TOKEN_REVOCATION_STRICT`` is truthy, a Redis error while revocation
    is CONFIGURED fails closed (treat the token as revoked) instead of fail-open.
    Off by default (a Redis blip shouldn't lock everyone out); operators of
    high-assurance services set it so a revocation-store outage denies rather
    than silently admits potentially-revoked tokens."""
    return os.environ.get("TOKEN_REVOCATION_STRICT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


async def token_is_revoked(payload: dict[str, Any]) -> bool:
    """True if the decoded token has been revoked, checked against the shared
    denylist DB (``TOKEN_REVOCATION_REDIS_URL``). Returns False when that env is
    unset (revocation not enforced in this service). When it IS set, a Redis
    error fails open by default, or fails CLOSED (returns True) under
    ``TOKEN_REVOCATION_STRICT``. One-line adoption for a service's auth
    dependency: ``if await token_is_revoked(payload): raise HTTPException(401)``."""
    r = _revocation_redis()
    if r is None:
        return False
    return await is_revoked(r, payload, strict=_revocation_strict())


def _reset_revocation_redis_for_tests() -> None:
    global _rev_redis, _rev_redis_init
    _rev_redis, _rev_redis_init = None, False


async def revoke_jti(redis: Any, jti: str, ttl_seconds: int) -> None:
    """Revoke a single token by its ``jti`` for ``ttl_seconds`` (its remaining
    life). No-op for a missing jti or a non-positive TTL (already expired)."""
    if not jti or ttl_seconds <= 0:
        return
    await redis.set(f"{_JTI_PREFIX}{jti}", "1", ex=ttl_seconds)


async def revoke_user_tokens(
    redis: Any, sub: str, cutoff_ts: int, ttl_seconds: int
) -> None:
    """Revoke EVERY token for user ``sub`` issued at/before ``cutoff_ts`` (unix
    seconds). Used on password reset/change or admin "sign out everywhere".
    ``ttl_seconds`` should cover the longest possible token life so the marker
    outlives any token it must invalidate."""
    if not sub or ttl_seconds <= 0:
        return
    await redis.set(f"{_USER_PREFIX}{sub}", str(int(cutoff_ts)), ex=ttl_seconds)


async def is_revoked(redis: Any, payload: dict[str, Any], *, strict: bool = False) -> bool:
    """True if the decoded token ``payload`` has been revoked — by its ``jti``
    or by a user-level cutoff (its ``iat`` predates the user's revoke-all).

    On a Redis error: fail-open (return False + warn) by default; ``exp`` still
    bounds exposure. With ``strict=True`` a Redis error fails CLOSED (returns
    True → deny) — for services that must not admit a potentially-revoked token
    during a revocation-store outage. A token missing ``iat`` under an active
    user cutoff is always treated as revoked (a pre-jti legacy token can't be
    proven fresh)."""
    try:
        jti = payload.get("jti")
        if jti and await redis.get(f"{_JTI_PREFIX}{jti}"):
            return True
        sub = payload.get("sub")
        if sub:
            cutoff = await redis.get(f"{_USER_PREFIX}{sub}")
            if cutoff is not None:
                iat = payload.get("iat")
                if iat is None:
                    return True
                try:
                    return int(iat) < int(cutoff)
                except (TypeError, ValueError):
                    return True
    except Exception:  # noqa: BLE001 — revocation store outage
        logger.warning(
            "token_revocation_check_failed (strict=%s)", strict, exc_info=True
        )
        return strict  # fail-closed under strict, else fail-open
    return False
