"""Structured logging for SentinelBuild services.

The single place that wires logging for every service (hoisted from the one
copy that used to live in ``services/mit-stack/backend/shared/logging_config.py``
and was otherwise copy-pasted inline across the fleet). It is the logging peer of
``smart_llm.observability`` (metrics/traces) and ``smart_llm.service_runtime``
(health).

``configure_logging()`` wires structlog -> JSON on stdout AND, when an OTEL
collector endpoint is configured (``OTEL_EXPORTER_OTLP_ENDPOINT``), ships the same
records to it over OTLP so logs land in Loki correlated to traces by ``trace_id``.
Every line carries any contextvars bound via
``structlog.contextvars.bind_contextvars()`` (e.g. ``request_id``/``trace_id``/
``company_id``) plus the active OTEL trace/span id when a span is in scope.

Everything OTEL is optional and no-op-safe: with the ``[observability]`` extra
absent, or the endpoint unset, you still get JSON-to-stdout and nothing fails.

Usage (call once at process start, in ``main.py`` and ``worker.py``)::

    from smart_llm.logging_config import configure_logging

    configure_logging(service_name="user-master")
"""

from __future__ import annotations

import logging
import os
import sys

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

logger = logging.getLogger(__name__)


def _add_otel_trace_context(
    _: WrappedLogger, __: str, event_dict: EventDict
) -> EventDict:
    """Inject the active OTEL ``trace_id``/``span_id`` (hex) so a log line links
    to its trace (Grafana's Loki->Tempo correlation matches on ``trace_id``).

    No-op when opentelemetry is not installed or no span is active. An explicit
    ``trace_id`` already bound via contextvars wins (``setdefault``).
    """
    try:
        from opentelemetry import trace
    except Exception:
        return event_dict
    span = trace.get_current_span()
    ctx = span.get_span_context() if span is not None else None
    if ctx is not None and getattr(ctx, "is_valid", False):
        event_dict.setdefault("trace_id", format(ctx.trace_id, "032x"))
        event_dict.setdefault("span_id", format(ctx.span_id, "016x"))
    return event_dict


def _install_otlp_log_export(level: int, service_name: str | None) -> None:
    """Attach an OTLP log handler to the stdlib root logger when a collector
    endpoint is set (``OTEL_EXPORTER_OTLP_ENDPOINT``).

    Soft-fails to a no-op if the OTEL logs SDK isn't installed, so a service
    without the ``[observability]`` extra still starts and logs to stdout.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
            OTLPLogExporter,
        )
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
    except Exception as exc:  # optional dependency missing
        logger.info("otlp_logging_skipped: %s", exc)
        return

    attributes: dict[str, str] = {
        "service.name": service_name or os.getenv("OTEL_SERVICE_NAME") or "smart-llm",
        "deployment.environment": os.getenv("ENVIRONMENT", "production"),
    }
    resource = Resource.create(attributes)
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(provider)
    logging.getLogger().addHandler(
        LoggingHandler(level=level, logger_provider=provider)
    )
    logger.info("otlp_logging_enabled: endpoint=%s", endpoint)


def configure_logging(level: str = "INFO", *, service_name: str | None = None) -> None:
    """Wire structlog for JSON output (+ OTLP export when configured).

    Call once at startup. ``service_name`` labels OTLP-exported logs; when omitted
    it falls back to ``OTEL_SERVICE_NAME`` then ``"smart-llm"``.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # stdlib root logger — captures uvicorn, sqlalchemy, temporalio logs too.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_otel_trace_context,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    _install_otlp_log_export(log_level, service_name)
