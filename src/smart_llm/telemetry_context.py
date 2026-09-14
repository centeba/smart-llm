"""Per-request telemetry context: unify request/trace id + tenant in logs.

Complements ``smart_llm.observability`` (traces/metrics) and
``smart_llm.logging_config`` (structured logs). Mount the middleware AFTER
``install_observability`` so the OTEL span created by ``FastAPIInstrumentor``
already exists when we read its ``trace_id``::

    from smart_llm.observability import install_observability
    from smart_llm.telemetry_context import install_telemetry_context

    install_observability(app, service_name="user-master")
    install_telemetry_context(app)

For every request this binds ``request_id`` and (when tracing is active)
``trace_id`` into the structlog contextvars, so every log line emitted during the
request carries them, and echoes ``X-Request-ID`` back on the response. Auth
dependencies call :func:`bind_company` once the caller's tenant is known so
subsequent log lines (and the active span) carry ``company_id`` too.

All OTEL access is optional and no-op-safe.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Trace-Id"


def _current_trace_id() -> str | None:
    """Hex trace id of the active OTEL span, or None when tracing is off."""
    try:
        from opentelemetry import trace
    except Exception:
        return None
    span = trace.get_current_span()
    ctx = span.get_span_context() if span is not None else None
    if ctx is not None and getattr(ctx, "is_valid", False):
        return format(ctx.trace_id, "032x")
    return None


def bind_company(company_id: str | None) -> None:
    """Bind the caller's tenant onto the current log context and OTEL span.

    Call from an auth dependency once ``company_id`` is resolved. No-op for a
    falsy id (anonymous / pre-auth). ``company_id`` stays a structured log field
    and a span attribute — never a Prometheus label (cardinality).
    """
    if not company_id:
        return
    structlog.contextvars.bind_contextvars(company_id=company_id)
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is not None:
            span.set_attribute("company_id", company_id)
    except Exception:  # pragma: no cover - defensive
        pass


def install_telemetry_context(app: FastAPI) -> None:
    """Register the per-request context middleware on *app*."""

    @app.middleware("http")
    async def _telemetry_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        structlog.contextvars.clear_contextvars()
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        trace_id = _current_trace_id()
        if trace_id:
            structlog.contextvars.bind_contextvars(trace_id=trace_id)

        response = await call_next(request)

        response.headers[REQUEST_ID_HEADER] = request_id
        if trace_id:
            response.headers.setdefault(TRACE_ID_HEADER, trace_id)
        return response


__all__ = [
    "REQUEST_ID_HEADER",
    "TRACE_ID_HEADER",
    "bind_company",
    "install_telemetry_context",
]
