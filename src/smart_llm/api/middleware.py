"""
API security middleware for smart-llm.

Provides rate limiting, API key authentication, idempotent request replay, and
safe error handling.
"""

import base64
import hashlib
import inspect
import json
import logging
import os
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response, StreamingResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate Limiting Middleware (in-memory sliding window)
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    In-memory sliding window rate limiter.

    Tracks requests per client IP within a configurable time window.
    Returns HTTP 429 when the limit is exceeded.

    Args:
        app: The FastAPI/Starlette application.
        max_requests: Maximum number of requests per window (default: 60).
        window_seconds: Window duration in seconds (default: 60).
        exempt_paths: Set of paths exempt from rate limiting (default: {"/health"}).
    """

    def __init__(
        self,
        app: Any,
        max_requests: int = 60,
        window_seconds: int = 60,
        exempt_paths: set[str] | None = None,
    ):
        super().__init__(app)
        self.max_requests = int(os.getenv("SMART_LLM_RATE_LIMIT", max_requests))
        self.window_seconds = int(os.getenv("SMART_LLM_RATE_WINDOW", window_seconds))
        self.exempt_paths = exempt_paths or {"/health"}
        # client_key -> list of request timestamps
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _get_client_key(self, request: Request) -> str:
        """Extract client identifier from request."""
        # Check X-Forwarded-For for proxy/load balancer setups
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Use the first IP in the chain (original client)
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def _cleanup_old_requests(self, client_key: str, now: float) -> None:
        """Remove expired request timestamps."""
        cutoff = now - self.window_seconds
        self._requests[client_key] = [
            ts for ts in self._requests[client_key] if ts > cutoff
        ]

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Skip rate limiting for exempt paths
        if request.url.path in self.exempt_paths:
            return await call_next(request)

        client_key = self._get_client_key(request)
        now = time.time()

        self._cleanup_old_requests(client_key, now)

        if len(self._requests[client_key]) >= self.max_requests:
            logger.warning(f"Rate limit exceeded for client: {client_key}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please try again later.",
                },
                headers={
                    "Retry-After": str(self.window_seconds),
                },
            )

        self._requests[client_key].append(now)
        return await call_next(request)


# ---------------------------------------------------------------------------
# API Key Authentication
# ---------------------------------------------------------------------------

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _api_key_required() -> bool:
    """True when missing API-key configuration must FAIL (not silently disable
    auth): ``SMART_LLM_REQUIRE_API_KEY`` truthy, or ``ENVIRONMENT=production``.
    Guards against a prod deploy that forgot to set SMART_LLM_API_KEYS from
    silently running open."""
    if os.getenv("SMART_LLM_REQUIRE_API_KEY", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return True
    return os.getenv("ENVIRONMENT", "").strip().lower() == "production"


async def require_api_key(
    api_key: str = Security(API_KEY_HEADER),
) -> str:
    """
    FastAPI dependency that validates the X-API-Key header.

    Reads valid keys from the SMART_LLM_API_KEYS environment variable
    (comma-separated). If no keys are configured, authentication is disabled
    (development mode) and returns "anonymous" — UNLESS auth is required
    (``SMART_LLM_REQUIRE_API_KEY`` or ``ENVIRONMENT=production``), in which case
    the misconfiguration fails closed with a 500 rather than running open.

    Returns:
        The validated API key string, or "anonymous" if auth is disabled.

    Raises:
        HTTPException: 500 if keys are required but unconfigured; 401 if the key
        is missing or invalid.
    """
    expected_keys_raw = os.getenv("SMART_LLM_API_KEYS", "")
    expected_keys = [k.strip() for k in expected_keys_raw.split(",") if k.strip()]

    if not expected_keys:
        if _api_key_required():
            # Fail closed: don't silently serve unauthenticated in prod.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="API key authentication is required but SMART_LLM_API_KEYS is not configured",
            )
        # No keys configured = auth disabled (development mode)
        return "anonymous"

    if not api_key or api_key not in expected_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key


# ---------------------------------------------------------------------------
# Idempotency Middleware (Redis-backed request replay)
# ---------------------------------------------------------------------------

# Only these methods mutate state, so only they are eligible for replay.
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Response headers that must not be replayed verbatim (recomputed by Starlette
# or connection-scoped).
_UNSAFE_REPLAY_HEADERS = frozenset(
    {"content-length", "transfer-encoding", "connection", "keep-alive", "date"}
)

# Redis getter: sync or async, returns a redis.asyncio.Redis-like client (the
# per-service ``get_redis_pool`` / ``get_redis`` fits). Returning None disables
# the middleware for that request (graceful degradation).
RedisGetter = Callable[[], Any] | Callable[[], Awaitable[Any]]


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Uniform ``Idempotency-Key`` replay for mutating requests (SB-03).

    A client that retries a POST/PUT/PATCH/DELETE carrying the same
    ``Idempotency-Key`` header gets the **original** response replayed instead of
    the side effect running twice. Replaces per-endpoint ad-hoc dedup with one
    header contract across every service.

    Semantics (Stripe-style, fenced against concurrent retries):

    * No ``Idempotency-Key`` header, or a non-mutating method → pass through
      untouched (the feature is opt-in per request).
    * First request for a key → claim it in Redis (``SET NX``), run the handler,
      cache the response (status + safe headers + body) under the key, and return
      it with ``Idempotency-Replayed: false``.
    * A retry while the original is still running (claim present, no cached
      result yet) → ``409 Conflict`` (the client should back off and retry).
    * A retry after completion → the cached response, byte-for-byte, with
      ``Idempotency-Replayed: true``.
    * ``5xx`` responses and bodies over ``max_body_bytes`` are **not** cached —
      the claim is released so a genuine retry re-runs the handler.

    The key is bound to the request's credential (a hash of the Authorization /
    X-API-Key header) and to the method+path, so one tenant's key can never
    replay another's response, and the same key on a different route is distinct.

    Fail-open by design: if Redis is unavailable or errors, the request runs
    normally without replay protection (never a 500 from an infra blip).
    """

    def __init__(
        self,
        app: Any,
        redis_getter: RedisGetter | None = None,
        *,
        ttl_seconds: int = 86_400,
        max_body_bytes: int = 1_048_576,
        header_name: str = "Idempotency-Key",
        exempt_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._redis_getter = redis_getter
        self.ttl_seconds = int(os.getenv("SMART_LLM_IDEMPOTENCY_TTL", ttl_seconds))
        self.max_body_bytes = max_body_bytes
        self.header_name = header_name
        self.exempt_paths = exempt_paths or {"/health"}

    async def _client(self) -> Any | None:
        if self._redis_getter is None:
            return None
        try:
            client = self._redis_getter()
            if inspect.isawaitable(client):
                client = await client
            return client
        except Exception:  # noqa: BLE001 — infra blip → run without replay
            logger.warning("idempotency: redis getter failed; skipping", exc_info=True)
            return None

    def _storage_key(self, request: Request, idem_key: str) -> str:
        # Bind to credential + method + path so a key is scoped to one caller and
        # one endpoint (never a cross-tenant or cross-route replay).
        cred = request.headers.get("authorization") or request.headers.get("x-api-key") or ""
        cred_fp = hashlib.sha256(cred.encode("utf-8")).hexdigest()[:16]
        raw = f"{request.method}:{request.url.path}:{cred_fp}:{idem_key}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"idem:{digest}"

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        idem_key = request.headers.get(self.header_name)
        if (
            not idem_key
            or request.method not in _MUTATING_METHODS
            or request.url.path in self.exempt_paths
        ):
            return await call_next(request)

        client = await self._client()
        if client is None:
            return await call_next(request)  # fail-open

        key = self._storage_key(request, idem_key)

        # Claim the key. SET NX succeeds only for the first request.
        try:
            claimed = await client.set(
                key, json.dumps({"state": "pending"}), nx=True, ex=self.ttl_seconds
            )
        except Exception:  # noqa: BLE001
            logger.warning("idempotency: claim failed; running unguarded", exc_info=True)
            return await call_next(request)

        if not claimed:
            return await self._replay_or_conflict(client, key)

        # We own the claim: run the handler, then cache the result.
        try:
            response = await call_next(request)
        except Exception:
            # Handler raised → release the claim so a retry can re-run, then
            # let the error propagate to the app's exception handlers.
            await self._release(client, key)
            raise

        streaming = cast(StreamingResponse, response)
        body = b"".join([cast(bytes, chunk) async for chunk in streaming.body_iterator])
        cacheable = response.status_code < 500 and len(body) <= self.max_body_bytes
        if cacheable:
            await self._store(client, key, response, body)
        else:
            # Transient/oversized → don't cache; free the claim for a real retry.
            await self._release(client, key)

        replayed = Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
        replayed.headers["Idempotency-Replayed"] = "false"
        return replayed

    async def _store(self, client: Any, key: str, response: Response, body: bytes) -> None:
        safe_headers = [
            [k, v]
            for k, v in response.headers.items()
            if k.lower() not in _UNSAFE_REPLAY_HEADERS
        ]
        record = {
            "state": "done",
            "status": response.status_code,
            "headers": safe_headers,
            "media_type": response.media_type,
            "body_b64": base64.b64encode(body).decode("ascii"),
        }
        try:
            await client.set(key, json.dumps(record), ex=self.ttl_seconds)
        except Exception:  # noqa: BLE001 — caching is best-effort
            logger.warning("idempotency: store failed", exc_info=True)

    async def _release(self, client: Any, key: str) -> None:
        try:
            await client.delete(key)
        except Exception:  # noqa: BLE001
            logger.warning("idempotency: release failed", exc_info=True)

    async def _replay_or_conflict(self, client: Any, key: str) -> Response:
        try:
            raw = await client.get(key)
        except Exception:  # noqa: BLE001
            logger.warning("idempotency: lookup failed; conflict", exc_info=True)
            raw = None

        if raw is None:
            # Claim exists but expired between our SET and GET, or lookup failed.
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"detail": "Idempotent request could not be resolved; retry."},
            )

        record = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        if record.get("state") != "done":
            # Original still in flight — tell the client to back off.
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"detail": "A request with this Idempotency-Key is in progress."},
            )

        body = base64.b64decode(record["body_b64"])
        headers = {k: v for k, v in record.get("headers", [])}
        response = Response(
            content=body,
            status_code=record["status"],
            headers=headers,
            media_type=record.get("media_type"),
        )
        response.headers["Idempotency-Replayed"] = "true"
        return response


def add_idempotency_middleware(
    app: FastAPI,
    redis_getter: RedisGetter,
    **kwargs: Any,
) -> None:
    """Mount :class:`IdempotencyMiddleware` on ``app`` with the service's Redis
    getter. A thin wrapper so every service mounts it the same one-line way."""
    app.add_middleware(IdempotencyMiddleware, redis_getter=redis_getter, **kwargs)
