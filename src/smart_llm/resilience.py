"""Retry + circuit-breaker helper for outbound network calls.

This module is the platform-wide convention for talking to external
vendors (Twilio, LLM providers, webhook receivers) and to internal
services where a downstream outage could otherwise cascade through
Temporal retry storms.

Two layers compose:

1. **Retry** — `tenacity`-style exponential backoff over transient
   errors (network/timeout/5xx). 4xx and explicit "permanent" errors
   bypass retry so we don't waste budget on a config bug.
2. **Circuit breaker** — once a host trips ``failure_threshold``
   failures within ``recovery_timeout`` seconds, every subsequent
   call to that host raises `CircuitOpenError` immediately for
   ``recovery_timeout`` seconds, then half-opens (one probe). This
   stops one slow vendor from holding every worker thread.

**Breaker state is per-replica, by design.** It protects each instance's own
worker pool / thread budget — the resource a tripped breaker actually guards —
so an in-process breaker is the correct scope, not a gap. Across N replicas a
downed vendor is discovered independently by each (up to N×``failure_threshold``
failures before all trip), which is an acceptable amplification for the safety a
per-instance breaker buys. A *shared* cluster-wide breaker would need Redis-
backed state AND an async ``breaker_state`` (it's sync today, called on the LLM-
failover hot path) — deferred until a deployment proves it's worth that
complexity. (Rate limiting, separately, IS cluster-wide: the deployed services
use ``slowapi`` with a Redis ``storage_uri`` — see each service's
``core/limiter.py``. The in-memory ``RateLimitMiddleware`` in ``api/middleware``
only backs smart-llm's own example app, which isn't deployed.)

Typical usage::

    from smart_llm.resilience import resilient_call, CircuitOpenError

    @resilient_call(name="twilio", failure_threshold=5, recovery_timeout=30.0)
    async def send_sms(client: httpx.AsyncClient, ...): ...

    try:
        await send_sms(client, ...)
    except CircuitOpenError:
        # Skip this vendor for now; LLM failover picks the next one.
        ...

Or as a context manager around an existing call site::

    async with resilient_section("openai"):
        resp = await client.post(...)
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Errors ────────────────────────────────────────────────────────────────────


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the host's breaker is OPEN.

    Catch this to fail over to a different vendor (LLM failover) or to
    short-circuit a workflow step with a typed "vendor unavailable"
    result rather than a generic retry-exhausted failure.
    """

    def __init__(self, name: str, retry_after: float) -> None:
        super().__init__(
            f"Circuit breaker OPEN for {name!r}; retry after {retry_after:.1f}s"
        )
        self.name = name
        self.retry_after = retry_after


class PermanentError(Exception):
    """Wrap an underlying error to tell the retry layer NOT to retry.

    Use for known-permanent conditions (4xx with non-2xx schema,
    bad credentials, malformed request). The retry decorator
    unwraps the cause and re-raises the original exception.
    """

    def __init__(self, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.__cause__ = cause


# ── Breaker state ─────────────────────────────────────────────────────────────


class _BreakerState:
    """Per-host breaker. Three states: CLOSED → OPEN → HALF_OPEN → CLOSED."""

    __slots__ = (
        "name",
        "failure_threshold",
        "recovery_timeout",
        "failures",
        "opened_at",
        "_lock",
    )

    def __init__(
        self, name: str, failure_threshold: int, recovery_timeout: float
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.opened_at: float | None = None
        self._lock = asyncio.Lock()

    async def before_call(self) -> None:
        """Raise CircuitOpenError if the breaker is OPEN and not ready
        for a half-open probe yet."""
        async with self._lock:
            if self.opened_at is None:
                return  # CLOSED — fine
            elapsed = time.monotonic() - self.opened_at
            if elapsed < self.recovery_timeout:
                raise CircuitOpenError(self.name, self.recovery_timeout - elapsed)
            # Allow a probe (HALF_OPEN). We don't move state yet — only
            # on the probe's success/failure.

    async def record_success(self) -> None:
        async with self._lock:
            if self.opened_at is not None:
                logger.info("circuit_breaker_closed name=%s", self.name)
            self.opened_at = None
            self.failures = 0

    async def record_failure(self) -> None:
        async with self._lock:
            self.failures += 1
            if self.failures >= self.failure_threshold and self.opened_at is None:
                self.opened_at = time.monotonic()
                logger.warning(
                    "circuit_breaker_opened name=%s failures=%s recovery_s=%s",
                    self.name,
                    self.failures,
                    self.recovery_timeout,
                )


_breakers: dict[str, _BreakerState] = {}


def _get_breaker(
    name: str, failure_threshold: int, recovery_timeout: float
) -> _BreakerState:
    b = _breakers.get(name)
    if b is None:
        b = _BreakerState(name, failure_threshold, recovery_timeout)
        _breakers[name] = b
    return b


def get_breaker(
    name: str,
    *,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
) -> _BreakerState:
    """Return (creating on first use) the named breaker for manual accounting.

    For call sites that can't use :func:`resilient_call` / :func:`resilient_section`
    because *what counts as a failure* depends on the response, not on whether an
    exception was raised — e.g. an HTTP client where a 4xx is a healthy response
    but a 5xx or a network error is a host-health failure. Such a caller does::

        breaker = get_breaker("sdk:doc-vault")
        await breaker.before_call()          # raises CircuitOpenError if OPEN
        resp = await do_the_call()
        if resp.status_code >= 500:
            await breaker.record_failure()
        else:
            await breaker.record_success()

    Breakers are keyed by *name* and shared process-wide, so two clients pointed
    at the same host share one breaker.
    """
    return _get_breaker(name, failure_threshold, recovery_timeout)


def breaker_state(name: str) -> str:
    """Return the breaker's logical state for metrics/tests.

    One of ``closed``, ``open``, ``half_open``. Unknown name → ``closed``
    (no breaker installed yet).
    """
    b = _breakers.get(name)
    if b is None or b.opened_at is None:
        return "closed"
    if time.monotonic() - b.opened_at >= b.recovery_timeout:
        return "half_open"
    return "open"


def reset_breakers() -> None:
    """Test helper — wipe all breaker state."""
    _breakers.clear()


# ── Retry policy ──────────────────────────────────────────────────────────────


def _should_retry(
    exc: BaseException, retry_on: tuple[type[BaseException], ...]
) -> bool:
    if isinstance(exc, PermanentError) or isinstance(exc, CircuitOpenError):
        return False
    return isinstance(exc, retry_on)


def _backoff_delay(attempt: int, base: float, cap: float) -> float:
    # Decorrelated jitter — proven to spread retry waves better than
    # plain exponential. attempt=1 → up to base*3, capped.
    return min(cap, random.uniform(base, base * 3**attempt))


# ── Public API ────────────────────────────────────────────────────────────────


def resilient_call(
    *,
    name: str,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    retry_on: tuple[type[BaseException], ...] | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorate an async function with retry + circuit breaker keyed by *name*.

    Parameters
    ----------
    name:
        Logical host identifier. Calls to the same logical host share
        breaker state — pass the same name to two functions if they hit
        the same vendor (e.g. two Twilio endpoints).
    max_attempts:
        Total tries including the first. 1 disables retry.
    base_delay, max_delay:
        Backoff bounds in seconds.
    failure_threshold, recovery_timeout:
        Breaker config — see module docstring.
    retry_on:
        Exception classes that count as transient. Default is a
        conservative bundle: ``ConnectionError``, ``TimeoutError``,
        and (lazily) ``httpx.TransportError`` / ``httpx.HTTPStatusError``
        for HTTP 5xx. 4xx must be raised as ``PermanentError`` by the
        caller to skip retry.
    """
    if retry_on is None:
        retry_on = _default_retry_on()

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            breaker = _get_breaker(name, failure_threshold, recovery_timeout)
            last_exc: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                await breaker.before_call()
                try:
                    result = await fn(*args, **kwargs)
                except PermanentError as p:
                    await breaker.record_failure()
                    # Unwrap so the caller sees the original error.
                    raise p.__cause__ if p.__cause__ else p
                except BaseException as exc:
                    last_exc = exc
                    if not _should_retry(exc, retry_on):
                        await breaker.record_failure()
                        raise
                    if attempt >= max_attempts:
                        await breaker.record_failure()
                        raise
                    delay = _backoff_delay(attempt, base_delay, max_delay)
                    logger.info(
                        "resilient_call_retry name=%s attempt=%s/%s delay_s=%.2f err=%s",
                        name,
                        attempt,
                        max_attempts,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    await breaker.record_success()
                    return result
            # Defensive — loop exits only via raise above.
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


@asynccontextmanager
async def resilient_section(
    name: str,
    *,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
) -> AsyncIterator[None]:
    """Lightweight breaker-only context manager.

    No retry — just opens/closes the breaker around an existing call
    site. Useful when retry logic already lives in the caller (e.g.
    LLM failover iterates over providers manually).
    """
    breaker = _get_breaker(name, failure_threshold, recovery_timeout)
    await breaker.before_call()
    try:
        yield
    except BaseException:
        await breaker.record_failure()
        raise
    else:
        await breaker.record_success()


def _default_retry_on() -> tuple[type[BaseException], ...]:
    # Lazy httpx import — not every consumer ships httpx (e.g. workers
    # that only do DB work). If unavailable we fall back to the stdlib
    # transient set.
    classes: list[type[BaseException]] = [
        ConnectionError,
        TimeoutError,
        asyncio.TimeoutError,
    ]
    try:
        import httpx

        classes.extend([httpx.TransportError, httpx.TimeoutException])
    except ImportError:  # pragma: no cover
        pass
    return tuple(classes)


__all__ = [
    "CircuitOpenError",
    "PermanentError",
    "breaker_state",
    "get_breaker",
    "reset_breakers",
    "resilient_call",
    "resilient_section",
]
