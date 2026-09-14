"""Agent-native OpenTelemetry tracing for smart-llm.

``observability.py`` stands up the OTEL ``TracerProvider`` (when
``OTEL_EXPORTER_OTLP_ENDPOINT`` is set) and instruments FastAPI / httpx /
SQLAlchemy — *infrastructure* spans. This module adds the **agent-native** spans
on top: one span per agent operation, per model call, per agent-loop cycle, and
per tool call, following GenAI semantic conventions and tagged per tenant, so a
trace in Langfuse / Jaeger / X-Ray shows what the agent actually did and carries
the same token/cost numbers as the ``ai_usage_events`` billing ledger.

Everything here is **no-op-safe and fail-open**: if ``opentelemetry`` isn't
installed (it lives in the ``observability`` extra) or no tracer provider is
configured, the helpers do nothing and never raise. Tracing must never break a
user-facing call.

Two shapes are provided:

* ``model_call_span`` / ``cycle_span`` / ``tool_call_span`` — context managers
  for wrapping a small region (``with model_call_span(...):``).
* ``start_span`` → :class:`_SpanHandle` — a manual start/end handle for
  bracketing a long method body (e.g. ``Agent.analyze``) without reindenting it
  under a ``with``.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

try:  # opentelemetry-api ships with the ``observability`` extra.
    from opentelemetry import trace as _otel_trace

    _OTEL = True
except Exception:  # pragma: no cover - exercised only without the extra
    _otel_trace = None  # type: ignore[assignment]
    _OTEL = False


# ── GenAI semantic-convention attribute keys ────────────────────────────────
_GEN_AI_SYSTEM = "gen_ai.system"
_GEN_AI_OPERATION = "gen_ai.operation.name"
_GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
_GEN_AI_USAGE_INPUT = "gen_ai.usage.input_tokens"
_GEN_AI_USAGE_OUTPUT = "gen_ai.usage.output_tokens"
_GEN_AI_TOOL_NAME = "gen_ai.tool.name"


def tracing_enabled() -> bool:
    """True when opentelemetry is importable (a provider may still be no-op)."""
    return _OTEL


def get_tracer() -> Any:
    """Return the ``smart_llm`` tracer, or ``None`` when OTEL is unavailable."""
    if not _OTEL:
        return None
    try:
        return _otel_trace.get_tracer("smart_llm")
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("tracing: get_tracer failed: %s", exc)
        return None


def _apply_attrs(span: Any, attributes: dict[str, Any] | None) -> None:
    if span is None or not attributes:
        return
    for key, value in attributes.items():
        if value is None:
            continue
        try:
            span.set_attribute(key, value)
        except Exception:  # pragma: no cover - defensive
            pass


def _set(span: Any, key: str, value: Any) -> None:
    if span is None or value is None:
        return
    try:
        span.set_attribute(key, value)
    except Exception:  # pragma: no cover - defensive
        pass


def _mark_error(span: Any, exc: BaseException) -> None:
    if span is None:
        return
    try:
        span.record_exception(exc)
        span.set_status(
            _otel_trace.Status(_otel_trace.StatusCode.ERROR, str(exc))
        )
    except Exception:  # pragma: no cover - defensive
        pass


# ── Manual span handle (bracket a method body, no reindent) ──────────────────


class _SpanHandle:
    """A started span whose lifecycle the caller ends explicitly.

    No-op-safe: when tracing is off, ``span`` is ``None`` and every method does
    nothing. The span is set as the *current* span between start and ``end`` so
    inner ``*_span`` calls nest under it automatically.
    """

    __slots__ = ("_cm", "span")

    def __init__(self, cm: Any, span: Any):
        self._cm = cm
        self.span = span

    def set(self, key: str, value: Any) -> None:
        _set(self.span, key, value)

    def error(self, exc: BaseException) -> None:
        _mark_error(self.span, exc)

    def end(self) -> None:
        if self._cm is None:
            return
        try:
            self._cm.__exit__(None, None, None)
        except Exception:  # pragma: no cover - defensive
            pass
        finally:
            self._cm = None
            self.span = None


def start_span(name: str, attributes: dict[str, Any] | None = None) -> _SpanHandle:
    """Start a current span and return a handle. Always safe; call ``.end()``."""
    tracer = get_tracer()
    if tracer is None:
        return _SpanHandle(None, None)
    try:
        cm = tracer.start_as_current_span(name)
        span = cm.__enter__()
        _apply_attrs(span, attributes)
        return _SpanHandle(cm, span)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("tracing: start_span(%s) failed: %s", name, exc)
        return _SpanHandle(None, None)


# ── Context-manager spans for small regions ──────────────────────────────────


@contextmanager
def _span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    handle = start_span(name, attributes)
    try:
        yield handle.span
    except Exception as exc:
        handle.error(exc)
        raise
    finally:
        handle.end()


def agent_operation_span(
    operation: str,
    *,
    agent_name: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    company_id: Any = None,
    agent_id: Any = None,
    user_id: Any = None,
) -> _SpanHandle:
    """Start the top-level span for one agent operation (analyze / stream / …).

    Returns a :class:`_SpanHandle` so the caller can bracket the whole method
    body and set usage attributes before ending it.
    """
    return start_span(
        f"agent.{operation}",
        {
            _GEN_AI_OPERATION: operation,
            _GEN_AI_SYSTEM: provider,
            _GEN_AI_REQUEST_MODEL: model,
            "gen_ai.agent.name": agent_name,
            "sentinelbuild.company_id": _s(company_id),
            "sentinelbuild.agent_id": _s(agent_id),
            "sentinelbuild.user_id": _s(user_id),
        },
    )


@contextmanager
def model_call_span(provider: str | None, model: str | None) -> Iterator[Any]:
    """Span around a single provider SDK call."""
    with _span(
        "gen_ai.chat",
        {
            _GEN_AI_OPERATION: "chat",
            _GEN_AI_SYSTEM: provider,
            _GEN_AI_REQUEST_MODEL: model,
        },
    ) as span:
        yield span


@contextmanager
def cycle_span(iteration: int) -> Iterator[Any]:
    """Span around one agent-loop iteration."""
    with _span("agent.cycle", {"sentinelbuild.cycle": iteration}) as span:
        yield span


@contextmanager
def tool_call_span(tool_name: str, *, risk: str | None = None) -> Iterator[Any]:
    """Span around one tool dispatch. Set ``sentinelbuild.tool.decision`` etc.
    on the yielded span from the caller."""
    with _span(
        "gen_ai.execute_tool",
        {
            _GEN_AI_OPERATION: "execute_tool",
            _GEN_AI_TOOL_NAME: tool_name,
            "sentinelbuild.tool.risk": risk,
        },
    ) as span:
        yield span


def set_usage_attributes(
    span: Any,
    *,
    usage: dict[str, Any] | None = None,
    cost_usd: Any = None,
    pii_masking: dict[str, Any] | None = None,
) -> None:
    """Stamp token counts (+ cost, + PII summary) onto a span, GenAI-style.

    Accepts a raw span or a :class:`_SpanHandle`; both are handled. Safe when
    ``span`` is ``None`` or tracing is off.
    """
    target = span.span if isinstance(span, _SpanHandle) else span
    if target is None:
        return
    usage = usage or {}
    _set(target, _GEN_AI_USAGE_INPUT, int(usage.get("input_tokens", 0) or 0))
    _set(target, _GEN_AI_USAGE_OUTPUT, int(usage.get("output_tokens", 0) or 0))
    if cost_usd is not None:
        try:
            _set(target, "sentinelbuild.cost_usd", float(cost_usd))
        except (TypeError, ValueError):
            pass
    if pii_masking:
        _set(target, "sentinelbuild.pii.policy", str(pii_masking.get("policy", "")))
        _set(
            target,
            "sentinelbuild.pii.token_count",
            int(pii_masking.get("token_count", 0) or 0),
        )


def _s(value: Any) -> str | None:
    """Coerce an id (UUID/str/None) to a string attribute value."""
    return None if value is None else str(value)


__all__ = [
    "agent_operation_span",
    "cycle_span",
    "get_tracer",
    "model_call_span",
    "set_usage_attributes",
    "start_span",
    "tool_call_span",
    "tracing_enabled",
]
