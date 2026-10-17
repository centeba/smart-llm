"""Service-to-service ("internal") authentication: one header, one key.

Roadmap 2.3 Part 3. Services used to authenticate each other three ways —
``X-Internal-Key``, ``Authorization: Bearer <INTERNAL_SERVICE_SECRET>`` and
``X-API-Key`` — against two different secrets, with per-service fallbacks, so a
caller and a callee could disagree about which secret applied. The platform
now uses one: the ``X-Internal-Key`` header carrying ``INTERNAL_API_KEY``.

Verifiers use ``require_internal_key`` (a FastAPI dependency) or
``is_internal_caller``; senders use ``internal_headers``. The key is read from
the environment on every call, like the JWT settings in ``platform_auth``.
"""

import hmac
import os

from fastapi import Header, HTTPException, status

INTERNAL_KEY_HEADER = "X-Internal-Key"


def internal_key() -> str:
    """This service's ``INTERNAL_API_KEY`` ('' when unset)."""
    return os.environ.get("INTERNAL_API_KEY", "")


def is_internal_caller(provided: str | None) -> bool:
    """True if ``provided`` is the platform internal key (constant-time).
    Always False when no key is configured, so an unset key never matches an
    empty header."""
    expected = internal_key()
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


async def require_internal_key(
    x_internal_key: str | None = Header(default=None, alias=INTERNAL_KEY_HEADER),
) -> None:
    """FastAPI dependency for internal-only routes. 500 when this service has
    no key configured (fail closed rather than open), 401 otherwise on a
    missing or wrong key."""
    if not internal_key():
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Server misconfigured: no internal key",
        )
    if not is_internal_caller(x_internal_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal key")


def internal_headers() -> dict[str, str]:
    """Headers a service sends on an internal call."""
    return {INTERNAL_KEY_HEADER: internal_key()}


__all__ = [
    "INTERNAL_KEY_HEADER",
    "internal_headers",
    "internal_key",
    "is_internal_caller",
    "require_internal_key",
]
