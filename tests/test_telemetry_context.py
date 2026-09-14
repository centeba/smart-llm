"""Tests for the SentinelBuild-side observability emit rails.

Covers the structured logging config (`smart_llm.logging_config`) and the
per-request context middleware (`smart_llm.telemetry_context`). These are the
consumer-side glue that ships logs/traces to the (separate, self-contained)
observability platform over OTLP — so the tests assert JSON shape, contextvar
binding, and header propagation, not any platform internals.
"""

import json

import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from smart_llm.logging_config import configure_logging
from smart_llm.telemetry_context import (
    REQUEST_ID_HEADER,
    bind_company,
    install_telemetry_context,
)


def test_configure_logging_emits_json_with_contextvars(capsys) -> None:
    configure_logging(service_name="test-svc")
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="r-1", company_id="co-9")
    structlog.get_logger("t").info("an_event", k=1)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "an_event"
    assert payload["request_id"] == "r-1"
    assert payload["company_id"] == "co-9"
    assert payload["k"] == 1
    assert payload["level"] == "info"


def test_middleware_binds_and_echoes_request_id() -> None:
    configure_logging(service_name="test-svc")
    app = FastAPI()
    install_telemetry_context(app)

    seen: dict[str, object] = {}

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        seen.update(structlog.contextvars.get_contextvars())
        return {"ok": "1"}

    client = TestClient(app)
    resp = client.get("/ping", headers={REQUEST_ID_HEADER: "req-abc"})
    assert resp.status_code == 200
    # Incoming request id is honoured, bound into the log context, and echoed.
    assert resp.headers[REQUEST_ID_HEADER] == "req-abc"
    assert seen.get("request_id") == "req-abc"


def test_middleware_generates_request_id_when_absent() -> None:
    app = FastAPI()
    install_telemetry_context(app)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "1"}

    resp = TestClient(app).get("/ping")
    assert resp.headers.get(REQUEST_ID_HEADER)  # a generated id is present


def test_bind_company_is_noop_for_falsy() -> None:
    structlog.contextvars.clear_contextvars()
    bind_company(None)
    bind_company("")
    assert "company_id" not in structlog.contextvars.get_contextvars()
    bind_company("co-42")
    assert structlog.contextvars.get_contextvars().get("company_id") == "co-42"
