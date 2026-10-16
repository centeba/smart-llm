"""The platform's one "current user from a bearer token" dependency (roadmap 2.1).

Services used to each carry their own copy, and the copies had drifted: 401 vs
403 for the same failure, different company claims, revocation checked in some
and not others. This is the single implementation they swap to.

The contract:

* Every token failure — missing, malformed, expired, revoked, a non-``full``
  scope, no ``exp``, bad claims — is **401** with ``WWW-Authenticate: Bearer``;
  an expired token also carries ``X-Auth-Error: token_expired`` (what the chassis
  session-expiry handler keys on). 403 is left for permission checks.
* No verification key at all (no JWKS URL or public key) is a 500: fail closed
  rather than accept.
* The company is read from ``company_id``, then ``org``, then ``cid``.
* Platform admin: ``system_admin`` or ``platform_admin``. Company admin:
  ``company_admin`` or ``system_admin`` — ``platform_admin`` is a builder role,
  not a company admin.

Tokens are RS256, verified with user-master's public key (roadmap 2.3). Each
service passes its own RLS ``stamp`` (its ``set_current_org`` /
``set_bypass_rls`` policy), so who bypasses RLS stays out of this library.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from smart_llm.platform_auth import decode_platform_token, platform_auth_configured
from smart_llm.token_revocation import token_is_revoked

PLATFORM_ADMIN_ROLES = frozenset({"system_admin", "platform_admin"})
COMPANY_ADMIN_ROLES = frozenset({"company_admin", "system_admin"})
DEFAULT_ROLE = "member"
_COMPANY_CLAIMS = ("company_id", "org", "cid")


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller, as the token describes them."""

    user_id: uuid.UUID
    company_id: uuid.UUID | None
    role: str
    email: str
    #: The verified token payload, for service-specific claims (office scope,
    #: enabled packs, company type, ...). Empty for a user built directly.
    claims: Mapping[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> uuid.UUID:
        """Alias of ``user_id``; the smart-llm router factories read ``.id``."""
        return self.user_id

    @property
    def is_platform_admin(self) -> bool:
        return self.role in PLATFORM_ADMIN_ROLES

    @property
    def is_company_admin(self) -> bool:
        return self.role in COMPANY_ADMIN_ROLES


Stamp = Callable[[CurrentUser], None]


def user_from_claims(payload: Mapping[str, Any]) -> CurrentUser:
    """Build a ``CurrentUser`` from a verified payload.

    Raises ``ValueError`` when ``sub`` is missing or ``sub`` / the company
    claim is not a UUID.
    """
    sub = payload.get("sub")
    if not sub:
        raise ValueError("token has no sub")
    company = next((payload[c] for c in _COMPANY_CLAIMS if payload.get(c)), None)
    return CurrentUser(
        user_id=uuid.UUID(str(sub)),
        company_id=uuid.UUID(str(company)) if company else None,
        role=str(payload.get("role") or DEFAULT_ROLE),
        email=str(payload.get("email") or ""),
        claims=dict(payload),
    )


def _unauthorized(detail: str, *, expired: bool = False) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"}
    if expired:
        headers["X-Auth-Error"] = "token_expired"
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers=headers)


async def authenticate(token: str | None) -> CurrentUser:
    """Verify ``token`` and return its user; raise 401 (or 500 if misconfigured).

    For callers that hold a raw token rather than a request — WebSocket and
    streaming resolvers. Does not stamp RLS; the dependencies below do.
    """
    if not token:
        raise _unauthorized("Not authenticated")
    if not platform_auth_configured():
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Server misconfigured: no JWT key"
        )
    try:
        payload = decode_platform_token(token, require=["sub", "exp"])
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired", expired=True) from None
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token") from None
    if await token_is_revoked(payload):
        raise _unauthorized("Token has been revoked")
    try:
        return user_from_claims(payload)
    except ValueError:
        raise _unauthorized("Invalid token claims") from None


# auto_error=False: a missing header gets the same 401 contract as a bad token,
# instead of HTTPBearer's own response (403 on older FastAPI versions).
_bearer = HTTPBearer(auto_error=False)


def current_user_dependency(stamp: Stamp) -> Callable[..., Awaitable[CurrentUser]]:
    """A FastAPI dependency: the authenticated user (401 otherwise), RLS stamped."""

    async def dependency(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> CurrentUser:
        user = await authenticate(credentials.credentials if credentials else None)
        stamp(user)
        return user

    return dependency


def optional_current_user_dependency(
    stamp: Stamp,
) -> Callable[..., Awaitable[CurrentUser | None]]:
    """Like ``current_user_dependency`` for routes that also serve anonymous
    callers: ``None`` when there is no usable token. A misconfigured server
    (500) still raises — it must not quietly turn every caller anonymous."""

    async def dependency(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> CurrentUser | None:
        if credentials is None:
            return None
        try:
            user = await authenticate(credentials.credentials)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                return None
            raise
        stamp(user)
        return user

    return dependency


__all__ = [
    "COMPANY_ADMIN_ROLES",
    "DEFAULT_ROLE",
    "PLATFORM_ADMIN_ROLES",
    "CurrentUser",
    "Stamp",
    "authenticate",
    "current_user_dependency",
    "optional_current_user_dependency",
    "user_from_claims",
]
