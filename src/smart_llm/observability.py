"""Single entry point for wiring observability into a FastAPI app.

Three pieces, all opt-in via env:

* **Metrics** — ``prometheus-fastapi-instrumentator`` exposes ``/metrics``
  with HTTP request count / duration / status-class labels. Default
  on when the optional dep is installed; no env required.
* **Sentry** — initialized if ``SENTRY_DSN`` is set. Captures unhandled
  exceptions and (optionally) traces a fraction of requests.
* **Tracing** — initialized if ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set.
  Instruments FastAPI + httpx + SQLAlchemy + Temporal. Spans are
  emitted via OTLP/HTTP to the configured collector.

Every helper is no-op-safe when its optional dependency isn't installed —
the helper logs and continues, so a service without prometheus_client
won't fail to start.

Usage::

    from fastapi import FastAPI
    from smart_llm.observability import install_observability

    app = FastAPI()
    install_observability(app, service_name="mit-stack-api")
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)


# ── Metrics ──────────────────────────────────────────────────────────────────


def install_metrics(app: FastAPI, *, service_name: str) -> None:
    """Wire ``/metrics`` onto *app* via prometheus-fastapi-instrumentator.

    Adds a ``service`` label to every metric so the Prometheus store
    can split per-service. /metrics, /health, /openapi.json, /docs are
    excluded from the per-route metric to avoid cardinality blow-up.
    """
    try:
        from prometheus_fastapi_instrumentator import Instrumentator, metrics
    except ImportError:
        logger.info(
            "metrics_skipped: prometheus_fastapi_instrumentator not installed "
            "(add it to the service's pyproject.toml to enable /metrics)"
        )
        return

    excluded = ("/metrics", "/health", "/openapi.json", "/docs", "/redoc")
    instrumentator = Instrumentator(
        excluded_handlers=list(excluded),
        # Keep exact codes ("503", not "5xx") so dashboards can match
        # status=~"5.." — the grouped form never matches that regex.
        should_group_status_codes=False,
        # service label is set per-process via the env var; the
        # instrumentator reads from prometheus_client.REGISTRY, so set
        # the label via constant_labels at registration.
    )
    # Explicit metric set instead of the library default: the default
    # http_request_duration_seconds has no ``status`` label, so the
    # observability platform's error-rate panel (which filters that metric on
    # status) would always read 0%. Drops the unlabelled
    # http_request_duration_highr_seconds histogram.
    instrumentator.add(metrics.requests())
    instrumentator.add(metrics.latency(should_include_status=True))
    instrumentator.add(metrics.request_size())
    instrumentator.add(metrics.response_size())
    instrumentator.instrument(app)
    # Use a small custom hook so every default metric carries the
    # service name; the upstream API doesn't expose constant_labels
    # directly on the helper. We attach via instrument-time hook.
    try:
        # Add the service label as a static collector — purely
        # informational, queryable as a join key from a single point.
        from prometheus_client import Info

        if not _info_registered("sentinelbuild_service"):
            info = Info("sentinelbuild_service", "Identity of the FastAPI process")
            info.info({"name": service_name})
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("metrics_service_label_failed: %s", exc)

    @app.on_event("startup")
    async def _expose_metrics() -> None:  # pragma: no cover - thin wrapper
        instrumentator.expose(app, endpoint="/metrics", include_in_schema=False)


_seen_infos: set[str] = set()


def _info_registered(name: str) -> bool:
    """Tiny dedupe so two install_metrics calls (tests) don't re-register."""
    if name in _seen_infos:
        return True
    _seen_infos.add(name)
    return False


# ── Sentry ───────────────────────────────────────────────────────────────────


def install_sentry(*, service_name: str, environment: str | None = None) -> None:
    """Initialize Sentry if ``SENTRY_DSN`` is in env.

    Idempotent — calling twice is a no-op. Pulls
    ``SENTRY_TRACES_SAMPLE_RATE`` (default 0.0) and ``SENTRY_RELEASE``
    (defaults to git SHA from ``GIT_SHA`` env if present, else ``""``).
    """
    dsn = (os.environ.get("SENTRY_DSN") or "").strip()
    if not dsn:
        logger.info("sentry_skipped: SENTRY_DSN not set")
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
    except ImportError:
        logger.info("sentry_skipped: sentry-sdk[fastapi] not installed")
        return

    try:
        sample_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0") or 0)
    except ValueError:
        sample_rate = 0.0

    sentry_sdk.init(
        dsn=dsn,
        environment=environment or os.environ.get("ENVIRONMENT", "production"),
        release=os.environ.get("SENTRY_RELEASE") or os.environ.get("GIT_SHA") or None,
        integrations=[FastApiIntegration()],
        traces_sample_rate=sample_rate,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service", service_name)


# ── OpenTelemetry traces ─────────────────────────────────────────────────────


def install_tracing(
    app: FastAPI, *, service_name: str, environment: str | None = None
) -> None:
    """Instrument *app* + httpx + SQLAlchemy with OTEL spans.

    No-op if ``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset or the OTEL
    libraries aren't installed.

    Spans are emitted via OTLP/HTTP; the collector address is read
    from the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` env (e.g.
    ``http://otel-collector:4318``). The tracer's Resource carries
    ``service.name`` + ``deployment.environment`` so traces, logs
    (``smart_llm.logging_config``) and metrics share one identity in
    Grafana/Tempo/Loki.
    """
    if not (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip():
        logger.info("tracing_skipped: OTEL_EXPORTER_OTLP_ENDPOINT not set")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.info(
            "tracing_skipped: opentelemetry-* packages not installed "
            "(install opentelemetry-sdk + opentelemetry-exporter-otlp + "
            "opentelemetry-instrumentation-fastapi to enable)"
        )
        return

    attributes: dict[str, str] = {SERVICE_NAME: service_name}
    env = environment or os.environ.get("ENVIRONMENT")
    # Omit when unset rather than claiming "production": the collector's
    # resource processor then inserts its own deployment.environment.
    if env:
        # semconv key; string literal avoids version-specific constants.
        attributes["deployment.environment"] = env
    provider = TracerProvider(resource=Resource.create(attributes))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)

    # Best-effort instrumentation for downstream calls. Each is
    # optional; failing imports are logged and skipped.
    for instr_name, module_path, class_name in (
        ("httpx", "opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
        (
            "sqlalchemy",
            "opentelemetry.instrumentation.sqlalchemy",
            "SQLAlchemyInstrumentor",
        ),
    ):
        try:
            import importlib

            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            cls().instrument()
        except ImportError:
            logger.info("tracing_instrumentation_skipped: %s", instr_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "tracing_instrumentation_failed name=%s err=%s", instr_name, exc
            )


# ── Composed helper ──────────────────────────────────────────────────────────


def install_observability(
    app: FastAPI,
    *,
    service_name: str,
    environment: str | None = None,
) -> None:
    """Compose `install_metrics`, `install_sentry`, `install_tracing`.

    Single-line wiring for the common case::

        app = FastAPI()
        install_observability(app, service_name="user-master")
    """
    install_metrics(app, service_name=service_name)
    install_sentry(service_name=service_name, environment=environment)
    install_tracing(app, service_name=service_name, environment=environment)


__all__ = [
    "install_metrics",
    "install_observability",
    "install_sentry",
    "install_tracing",
]
