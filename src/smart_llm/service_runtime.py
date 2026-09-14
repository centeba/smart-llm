"""Shared FastAPI runtime helpers used by every SentinelBuild service.

Lives in ``smart_llm`` (the leaf package every service Dockerfile installs)
so services + the scaffold template can use it without taking a new dep —
same rationale as ``smart_llm.observability`` / ``smart_llm.resilience``.

Provides:
- :func:`resolve_pool_sizing` — replica-aware SQLAlchemy pool budget.
- :func:`add_readiness_route` — deep ``/healthz`` (DB/Redis/Temporal probes).
- :func:`install_exception_handler` — uniform, non-leaking 500 envelope.
- ``AUTH_ERROR_HEADER`` / ``AUTH_ERROR_TOKEN_EXPIRED`` — the machine signal a
  JWT dependency attaches to its 403 so clients detect session expiry without
  string-matching the human-readable ``detail``.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid importing FastAPI at module load for non-web callers
    from datetime import timedelta

    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# ── Auth-error signal (used by the JWT deps; read by the frontend) ───────────
AUTH_ERROR_HEADER = "X-Auth-Error"
#: invalid OR expired token — the chassis treats this as "session expired"
AUTH_ERROR_TOKEN_EXPIRED = "token_expired"


# ── Replica-aware DB pool sizing ─────────────────────────────────────────────
def resolve_pool_sizing(pool_size: int, max_overflow: int) -> tuple[int, int]:
    """Scale a *single-replica* pool budget down by ``REPLICA_COUNT``.

    Service pool defaults are tuned for one replica; running N replicas with
    the full budget can exhaust Postgres ``max_connections``. With
    ``REPLICA_COUNT=N`` each replica gets ``floor(budget / N)`` (min 1) so the
    cluster total stays within budget. Defaults to 1 (unchanged) when unset.
    """
    try:
        replicas = max(1, int(os.environ.get("REPLICA_COUNT", "1")))
    except (TypeError, ValueError):
        replicas = 1
    if replicas <= 1:
        return pool_size, max_overflow
    eff_pool = max(1, pool_size // replicas)
    eff_overflow = max(0, max_overflow // replicas)
    logger.info(
        "db_pool_scaled replicas=%d pool_size=%d->%d max_overflow=%d->%d",
        replicas,
        pool_size,
        eff_pool,
        max_overflow,
        eff_overflow,
    )
    return eff_pool, eff_overflow


def migration_db_url(url: str) -> str:
    """Swap the DB credentials for a migration identity when
    ``MIGRATION_DB_USER`` (and optionally ``MIGRATION_DB_PASSWORD``) are set,
    preserving the driver, host, port and database from ``url``.

    This enables the RLS activation split (HARDENING-PLAN A2): the app's RUNTIME
    connection uses a NON-superuser role (so ``FORCE ROW LEVEL SECURITY`` bites),
    while alembic migrations — which must ``CREATE TABLE`` / ``CREATE POLICY`` —
    keep running as the privileged owner. Call it on the URL an ``alembic/env.py``
    is about to hand to alembic. No-op (returns ``url`` unchanged) when
    ``MIGRATION_DB_USER`` is unset, so existing deploys behave exactly as before.
    """
    migration_user = os.environ.get("MIGRATION_DB_USER")
    if not migration_user:
        return url
    from sqlalchemy.engine import make_url

    parsed = make_url(url).set(username=migration_user)
    migration_password = os.environ.get("MIGRATION_DB_PASSWORD")
    if migration_password is not None:
        parsed = parsed.set(password=migration_password)
    return parsed.render_as_string(hide_password=False)


def graceful_shutdown_timeout() -> "timedelta":
    """Grace period a Temporal worker gives in-flight activities to finish on
    SIGTERM before they are cancelled (readiness gate 12 — drain, not drop).

    Without this, ``Worker``'s default is 0: on shutdown, in-flight activities
    are cancelled immediately and rely on Temporal redelivery — zero-drop, but
    a disruptive mid-activity kill. A non-zero timeout lets running activities
    complete for a bounded window first (zero-*disruption*).

    Read from ``TEMPORAL_GRACEFUL_SHUTDOWN_SECONDS`` (default 30). Keep it at or
    below the platform's own SIGTERM→SIGKILL grace so the worker isn't hard-
    killed mid-drain (Railway/K8s send SIGKILL after their termination grace).
    """
    from datetime import timedelta

    try:
        secs = max(0, int(os.environ.get("TEMPORAL_GRACEFUL_SHUTDOWN_SECONDS", "30")))
    except (TypeError, ValueError):
        secs = 30
    return timedelta(seconds=secs)


# ── Correlation id ───────────────────────────────────────────────────────────
def current_request_id() -> str | None:
    """Best-effort current request/trace id for log+response correlation.

    Reads the structlog ``request_id`` contextvar that the logging middleware
    binds (see ``smart_llm.logging_config`` / ``smart_llm.telemetry_context``).
    """
    try:
        import structlog

        rid = structlog.contextvars.get_contextvars().get("request_id")
        if rid:
            return str(rid)
    except Exception:  # noqa: BLE001 — observability must never break a request
        pass
    return None


# ── Uniform 500 handler ──────────────────────────────────────────────────────
def install_exception_handler(app: FastAPI, *, service_name: str) -> None:
    """Register a catch-all handler that returns a uniform, non-leaking 500.

    Body is ``{"error_code": "internal_error", "request_id": <id>}`` — never the
    exception message or stack trace. Logs with ``exc_info`` and best-effort
    captures to Sentry. FastAPI's ``HTTPException`` / validation handlers are
    more specific and keep their own (already-safe) behaviour.
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse

    log = logging.getLogger(service_name)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        rid = current_request_id()
        log.error(
            "unhandled_exception",
            exc_info=exc,
            extra={
                "path": request.url.path,
                "method": request.method,
                "request_id": rid,
            },
        )
        try:
            import sentry_sdk

            sentry_sdk.capture_exception(exc)
        except Exception:  # noqa: BLE001
            pass
        return JSONResponse(
            status_code=500,
            content={"error_code": "internal_error", "request_id": rid},
        )


# ── Deep readiness probe ─────────────────────────────────────────────────────
Check = Callable[[], Awaitable[object] | object]


async def _run_check(fn: Check, timeout: float) -> bool:
    try:
        result = fn()
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def add_readiness_route(
    app: FastAPI,
    *,
    service_name: str,
    checks: Mapping[str, Check],
    path: str = "/healthz",
    timeout: float = 3.0,
) -> None:
    """Register a deep readiness probe at ``path``.

    ``checks`` maps a dependency name to a (sync or async) callable that raises
    on failure. Returns 200 only if all pass, else 503, with a per-dependency
    body. Point the orchestrator's *readiness* probe here; keep *liveness*
    shallow (the existing ``/health``) so a transient dep blip doesn't trigger a
    restart loop. Helper check builders: :func:`db_check`, :func:`redis_check`,
    :func:`temporal_check`.
    """
    from fastapi.responses import JSONResponse

    @app.get(path, tags=["health"], include_in_schema=False)
    async def _readiness() -> JSONResponse:
        results: dict[str, str] = {}
        ok = True
        for name, fn in checks.items():
            passed = await _run_check(fn, timeout)
            results[name] = "ok" if passed else "fail"
            ok = ok and passed
        return JSONResponse(
            status_code=200 if ok else 503,
            content={
                "status": "ok" if ok else "degraded",
                "service": service_name,
                "checks": results,
            },
        )


def db_check(session_factory: Callable[[], object]) -> Check:
    """Readiness check: a ``SELECT 1`` via an async session factory.

    ``session_factory`` is the service's ``async_sessionmaker`` (called with no
    args to open a session context manager).
    """

    async def _c() -> None:
        from sqlalchemy import text

        async with session_factory() as session:  # type: ignore[attr-defined]  # duck-typed async_sessionmaker
            await session.execute(text("SELECT 1"))

    return _c


def redis_check(redis_getter: Callable[[], object]) -> Check:
    """Readiness check: ``PING`` a Redis client.

    ``redis_getter`` returns a client (or an awaitable that resolves to one) —
    tolerates both the sync-pool and async-accessor service conventions.
    """

    async def _c() -> None:
        client = redis_getter()
        if inspect.isawaitable(client):
            client = await client
        await client.ping()  # type: ignore[attr-defined]  # duck-typed redis client

    return _c


def temporal_check(client_getter: Callable[[], Awaitable[object] | object]) -> Check:
    """Readiness check: the Temporal client connects/resolves.

    ``client_getter`` is the service's ``get_temporal_client`` (typically async
    and cached). A successful connect proves the frontend is reachable.
    """

    async def _c() -> None:
        client = client_getter()
        if inspect.isawaitable(client):
            client = await client
        # Cheap server round-trip to confirm the cached client is live.
        svc = getattr(client, "service_client", None) or getattr(
            client, "workflow_service", None
        )
        if svc is not None and hasattr(svc, "check_health"):
            await svc.check_health()

    return _c


# ── Migrate-on-boot serialization ────────────────────────────────────────────
def acquire_migration_lock(
    connection: Any,
    *,
    key: int = 872_110,
    lock_timeout_ms: int = 30_000,
) -> bool:
    """Serialize concurrent ``alembic upgrade head`` across co-booting replicas.

    Every service still migrates-on-boot (the entrypoint runs migrations before
    binding). When >1 replica starts together — a rolling deploy or a scale-out —
    they race on the same schema, and Postgres DDL under concurrent alembic runs
    can deadlock or double-apply. Taking a **session-level advisory lock** on a
    shared ``key`` makes the migrations run one-at-a-time; the lock auto-releases
    when the migration connection closes, so no explicit unlock is needed.

    Best-effort by design: bounded by ``SET lock_timeout`` so a wedged holder
    can't hang boot forever. On timeout/error we log and return ``False``, and
    the caller falls through to an unserialized migration (today's behavior) —
    strictly no worse than not having the lock. Returns ``True`` when held.

    ``connection`` is a *synchronous* SQLAlchemy Connection (the async env.py
    files call this inside ``connection.run_sync(...)``, which hands over a sync
    connection), so ``exec_driver_sql`` is safe on every service's path.

    The two statements run inside their OWN committed transaction and the
    connection is left with **no open transaction** on return: both effects are
    session-scoped (plain ``SET``, not ``SET LOCAL``; ``pg_advisory_lock``, not
    the xact-scoped variant), so they persist past the commit, while every
    caller's next step — its ``with connection.begin():`` CREATE SCHEMA block or
    alembic's own ``context.begin_transaction()`` — needs a clean connection.
    Leaving SQLAlchemy's autobegun transaction dangling here would make that
    next ``begin()`` raise ``InvalidRequestError``.
    """
    try:
        with connection.begin():
            connection.exec_driver_sql(f"SET lock_timeout = '{int(lock_timeout_ms)}ms'")
            connection.exec_driver_sql(f"SELECT pg_advisory_lock({int(key)})")
        return True
    except Exception:  # noqa: BLE001 — best-effort; never block boot on the lock
        # Roll back any partial/autobegun state so the caller's own begin()
        # starts from a clean connection (we fall through unserialized).
        try:
            connection.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "acquire_migration_lock: could not acquire advisory lock %s within "
            "%dms; proceeding without migration serialization",
            key,
            lock_timeout_ms,
            exc_info=True,
        )
        return False


# ── Cross-replica one-shot guard ─────────────────────────────────────────────


async def run_once(
    redis: Any,
    name: str,
    *,
    ttl_seconds: int = 300,
    fail_open: bool = False,
) -> bool:
    """Return True for exactly one replica per boot window for one-shot work.

    A Redis ``SET NX EX`` claim lets a single replica run a shared startup
    side-effect (creating an index, seeding a row) instead of once-per-replica;
    the claim auto-expires after ``ttl_seconds`` so a later deploy re-runs it.

    ``fail_open`` controls behavior when Redis is unreachable:

    - ``False`` (default) — **fail closed**: return ``False`` (skip the work).
      Correct for work that must not run unguarded (e.g. anything with
      side effects other replicas could duplicate destructively).
    - ``True`` — return ``True`` so the caller still runs the task. Use only
      when running it more than once is provably harmless (idempotent
      ``CREATE ... IF NOT EXISTS`` DDL), and running it zero times would leave
      the system unbootstrapped.

    Pass a Redis client (this leaf package doesn't own a pool). Idempotent
    startup DDL should pass ``fail_open=True`` explicitly.
    """
    try:
        acquired = await redis.set(f"startup:once:{name}", "1", nx=True, ex=ttl_seconds)
        return bool(acquired)
    except Exception:
        logger.warning(
            "run_once(%s): redis unavailable; %s",
            name,
            "running anyway (fail_open)" if fail_open else "skipping (fail_closed)",
            exc_info=True,
        )
        return fail_open
