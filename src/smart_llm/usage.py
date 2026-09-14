"""Phase-E4: cost tracking + budget enforcement.

Every provider call is wrapped by :func:`record_usage` which inserts
a row into ``ai_usage_events`` and (when a budget is configured)
checks the running monthly total. Once the company hits 100% of its
budget the next call raises :class:`BudgetExceededError`.

Cost computation is intentionally simple and table-driven via
:data:`PRICING` — accurate enough for a soft monthly cap; precise
billing should defer to provider-side invoices. Hosts can override
prices by mutating the dict at startup.

The recorder is decoupled from the providers themselves: hosts call
``record_usage(...)`` after a successful completion, passing the
agent/skill/provider info plus token counts (Anthropic returns these
in ``response.usage``; OpenAI in ``response.usage``; Gemini in
``response.usage_metadata``). When token counts aren't available
(streaming) the cost is recorded as 0 and the row still anchors the
event for the audit trail.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID

# Money is exact decimal, never binary float (production-readiness gate 9).
# Per-event costs can be sub-cent (a cheap model at low token counts), so the
# ledger column carries more scale than the Numeric(12,4) budget ceilings it is
# summed against — 6 dp is comfortably below one-millionth of a dollar.
_MONEY = Numeric(14, 6)
_ZERO = Decimal("0")


def _to_decimal(value: Any) -> Decimal:
    """Coerce a number (possibly a float literal from PRICING or a provider) to
    Decimal via its string form, so no binary-float error is baked in."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


logger = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    """Raised when a company has exhausted its monthly AI budget.

    Workflow nodes catch this and route to the ``error`` branch (same
    convention as ``continue_on_error`` HTTP failures); admin REST
    endpoints surface it as HTTP 402 (Payment Required).
    """


# ── Per-provider/model pricing ($ per 1M tokens) ────────────────────────────
# Sourced from public price sheets as of 2026-04. Hosts can override by
# replacing entries at startup. Keys are lowercased.
PRICING: dict[str, tuple[float, float]] = {
    # (input_per_million, output_per_million)
    "anthropic:claude-sonnet-4-6": (3.00, 15.00),
    "anthropic:claude-opus-4-6": (15.00, 75.00),
    "anthropic:claude-haiku-4-5-20251001": (0.80, 4.00),
    "anthropic:claude-3-opus-20240229": (15.00, 75.00),
    "openai:gpt-4-turbo-preview": (10.00, 30.00),
    "openai:gpt-4o": (2.50, 10.00),
    "openai:gpt-4o-mini": (0.15, 0.60),
    "gemini:gemini-2.5-flash": (0.075, 0.30),
    "gemini:gemini-2.5-pro": (1.25, 5.00),
}


# Global conservative fallback (premium tier) used when a model isn't in
# PRICING and the provider has no known rates either. Over-estimating is the
# safe direction for a soft budget cap — better to gate slightly early than to
# silently accrue $0 for an unpriced model (M4).
_FALLBACK_RATES: tuple[float, float] = (15.00, 75.00)


def _fallback_rates_for(provider: str) -> tuple[float, float]:
    """Priciest known rate for the same provider, else the global fallback."""
    prov = f"{provider.lower()}:"
    same = [r for k, r in PRICING.items() if k.startswith(prov)]
    if same:
        return (max(r[0] for r in same), max(r[1] for r in same))
    return _FALLBACK_RATES


def estimate_cost_usd(
    provider: str, model: str, input_tokens: int, output_tokens: int
) -> Decimal:
    """Look up ``PRICING`` and compute USD cost as an exact :class:`Decimal`.

    On a miss, fall back to a conservative (over-)estimate so an unpriced model
    still accrues budget — a soft cap that counts $0 for new models is no cap.

    Returns Decimal (not float): these per-call costs are summed into a monthly
    total that gates spend, so binary-float drift is not acceptable.
    """
    key = f"{provider.lower()}:{(model or '').lower()}"
    rates = PRICING.get(key)
    if rates is None:
        rates = _fallback_rates_for(provider)
        if not getattr(estimate_cost_usd, "_warned", set()):
            estimate_cost_usd._warned = set()  # type: ignore[attr-defined]
        warned = estimate_cost_usd._warned  # type: ignore[attr-defined]
        if key not in warned:
            warned.add(key)
            logger.warning(
                "usage: no PRICING entry for %r — using conservative fallback "
                "%s (add it to PRICING for accurate billing)",
                key,
                rates,
            )
    in_rate, out_rate = (_to_decimal(rates[0]), _to_decimal(rates[1]))
    return (input_tokens * in_rate + output_tokens * out_rate) / Decimal(1_000_000)


# ── ORM factory ─────────────────────────────────────────────────────────────


def make_usage_model(Base: type) -> type:  # host's declarative Base
    """Return an ``AIUsageEvent`` mapped against ``Base.metadata``.

    Mirrors the ``make_ai_models`` factory pattern so hosts can attach
    the table to their own metadata without import-cycle headaches.
    """

    class AIUsageEvent(Base):  # type: ignore[misc]  # host-provided declarative Base is dynamic; mypy cannot check it
        __tablename__ = "ai_usage_events"

        id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
        company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
        # The tenant whose action *triggered* the spend (grants/multi-tenant —
        # alembic 014). NOT NULL in the table; defaults to company_id when the
        # caller doesn't distinguish a separate triggering tenant. Omitting it
        # (the prior bug) made every insert fail the NOT-NULL constraint, so no
        # usage row was ever written.
        triggering_company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
        # The individual user whose action drove the spend — populated from the
        # caller's JWT (or the internal-call body for service callers). Nullable:
        # system/cron-triggered runs and legacy rows have no user. Indexed so the
        # platform billing view can group spend per user.
        user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
        agent_id = Column(UUID(as_uuid=True), nullable=True, index=True)
        skill_id = Column(UUID(as_uuid=True), nullable=True, index=True)
        provider = Column(String(40), nullable=False)
        model = Column(String(120), nullable=False)
        input_tokens = Column(Integer, nullable=False, default=0)
        output_tokens = Column(Integer, nullable=False, default=0)
        usd_cost = Column(_MONEY, nullable=False, default=_ZERO)
        # Exactly-once recording key. When a caller supplies one (e.g. the
        # provider request id), a retried call cannot double-count spend: the
        # UNIQUE constraint rejects the second insert and record_usage returns
        # the already-recorded cost. NULL is allowed and multiple NULLs don't
        # collide (SQL treats NULLs as distinct), so pre-existing rows and
        # callers that don't supply a key are unaffected.
        idempotency_key = Column(String(120), nullable=True, unique=True)
        # Counts-only PII-masking summary for this call (never any PII values):
        # {policy, token_count, per_type_counts, vision_blocked, fail_closed, …}.
        # NULL when masking was off or the provider wasn't the masking firewall.
        # Generic JSON type so it maps onto the postgres JSONB column (added by
        # each host's migration) and onto the sqlite test DB alike.
        pii_masking = Column(JSON, nullable=True)
        created_at = Column(
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(timezone.utc),
            index=True,
        )

    return AIUsageEvent


# ── Recorder + budget guard ─────────────────────────────────────────────────


@dataclass
class UsageContext:
    """Bundle of identifiers passed to :func:`record_usage`."""

    company_id: str
    agent_id: str | None
    skill_id: str | None
    provider: str
    model: str
    # Tenant that triggered the spend (alembic 014). Defaults to company_id in
    # record_usage when the caller doesn't set a distinct triggering tenant.
    triggering_company_id: str | None = None
    # The individual user whose action drove the spend (from the caller's JWT /
    # internal-call body). None for system/cron-triggered runs.
    user_id: str | None = None


async def record_usage(
    session: Any,
    UsageModel: Any,
    ctx: UsageContext,
    *,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | Decimal | None = None,
    idempotency_key: str | None = None,
    pii_masking: dict[str, Any] | None = None,
) -> Decimal:
    """Insert one usage row and return the recorded cost in USD (Decimal).

    ``cost_usd`` is a provider-reported authoritative cost. Gateways like
    OpenRouter return the exact charge for the request (which model actually
    ran, at that provider's live rate) — far more accurate than our static
    :data:`PRICING` table, and it sidesteps the fallback entirely for the
    ~400 models we'd otherwise have to keep priced by hand. When it's
    ``None`` (direct providers today) we fall back to the table estimate.

    ``idempotency_key`` makes recording exactly-once: if a row with this key
    already exists (a retried provider call), no second row is written and the
    already-recorded cost is returned, so spend is never double-counted.
    """
    if cost_usd is not None and _to_decimal(cost_usd) >= 0:
        cost = _to_decimal(cost_usd)
    else:
        cost = estimate_cost_usd(ctx.provider, ctx.model, input_tokens, output_tokens)

    # Fast path for the common retry case: a prior row with this key already
    # recorded the spend — return its cost without inserting again. The UNIQUE
    # constraint is the real guarantee for a truly-concurrent duplicate (the
    # loser gets an IntegrityError and retries into this branch).
    if idempotency_key is not None:
        prior = (
            await session.execute(
                select(UsageModel.usd_cost).where(
                    UsageModel.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if prior is not None:
            return _to_decimal(prior)

    # Default the triggering tenant to the billed company when not distinguished
    # (matches alembic 014's backfill). Required — the column is NOT NULL.
    triggering = ctx.triggering_company_id or ctx.company_id
    row = UsageModel(
        company_id=uuid.UUID(str(ctx.company_id)),
        triggering_company_id=uuid.UUID(str(triggering)),
        user_id=uuid.UUID(str(ctx.user_id)) if ctx.user_id else None,
        agent_id=uuid.UUID(str(ctx.agent_id)) if ctx.agent_id else None,
        skill_id=uuid.UUID(str(ctx.skill_id)) if ctx.skill_id else None,
        provider=ctx.provider.lower(),
        model=ctx.model or "",
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        usd_cost=cost,
        idempotency_key=idempotency_key,
        pii_masking=pii_masking,
    )
    session.add(row)
    await session.flush()
    return cost


async def get_month_to_date_spend(
    session: Any, UsageModel: Any, company_id: str
) -> Decimal:
    """Sum ``usd_cost`` for the current calendar month (UTC) as exact Decimal."""
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    stmt = select(func.coalesce(func.sum(UsageModel.usd_cost), _ZERO)).where(
        UsageModel.company_id == uuid.UUID(str(company_id)),
        UsageModel.created_at >= month_start,
    )
    res = await session.execute(stmt)
    return _to_decimal(res.scalar() or _ZERO)


async def assert_within_budget(
    session: Any,
    UsageModel: Any,
    company_id: str,
    *,
    monthly_budget_usd: float,
) -> None:
    """Raise :class:`BudgetExceededError` when the monthly cap is hit.

    ``monthly_budget_usd <= 0`` means "no cap" — the check returns
    immediately so the host doesn't incur a SQL round-trip on every
    call when budgets aren't configured.
    """
    if monthly_budget_usd is None or monthly_budget_usd <= 0:
        return
    cap = _to_decimal(monthly_budget_usd)
    spend = await get_month_to_date_spend(session, UsageModel, company_id)
    if spend >= cap:
        raise BudgetExceededError(
            f"Company {company_id} has spent ${spend:.2f} of its "
            f"${cap:.2f} monthly AI budget; further "
            "agent calls are blocked until next month or until the "
            "budget is raised."
        )
    if spend >= Decimal("0.8") * cap:
        # Soft warning — bubbles into the audit log via the host's
        # logger; the call still proceeds.
        logger.warning(
            "usage: company %s at %.0f%% of monthly budget ($%.2f / $%.2f)",
            company_id,
            100 * spend / cap,
            spend,
            cap,
        )


# ── Tenant gate (Phase F — hard cap with bell-icon alert) ──────────────────
#
# ``assert_llm_allowed_for_tenant`` is the platform-wide pre-call gate every
# service that invokes an LLM should run at the request boundary. It wraps
# ``assert_within_budget`` with three side effects that fire on the
# **first** cap trip per (company, month):
#
#   1) A NotificationDeliveryLog row is inserted so the existing chassis
#      bell-icon poll (``/api/v1/logs``) surfaces it as a normal
#      notification — no new endpoint or screen.
#   2) A JSON message is published to the Redis channel
#      ``alert:budget_exhausted:{company_id}``. The subscription bus
#      bridges this onto WS topic ``org.{X}.alert.budget_exhausted`` (see
#      ``subscription_bus.py::TOPIC_TO_REDIS_RULES``) so connected
#      sessions see the alert instantly.
#   3) ``BudgetExceededError`` is raised. HTTP routes map this to 429.
#
# Subsequent calls within the same month see a SET-NX'd Redis key, skip
# the side effects, and just raise. This keeps the bell from spamming a
# new row for every blocked call. The throttle key TTL targets the end
# of the UTC month so the alert resets cleanly when the cap resets.
#
# The helper accepts both the company-settings loader and the Redis
# client as injected dependencies so it stays decoupled from any
# particular service's plumbing — each host passes its local versions.
# When ``redis`` is None (e.g. tests, single-process dev) the side
# effects degrade to a structured log line; the raise still happens.


async def _seconds_until_month_end_utc() -> int:
    """Seconds remaining until the start of the next UTC calendar
    month. Used as the throttle key's TTL so the alert resets on the
    1st automatically without a cron sweep."""

    now = datetime.now(timezone.utc)
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return max(1, int((next_month - now).total_seconds()))


async def assert_llm_allowed_for_tenant(
    session: Any,
    *,
    company_id: str,
    UsageModel: Any,
    monthly_budget_usd: float,
    notification_log_model: Any | None = None,
    redis: Any = None,
) -> None:
    """Block an LLM call when the tenant's monthly cap is hit.

    Parameters
    ----------
    session, UsageModel, company_id, monthly_budget_usd
        Same shape as ``assert_within_budget`` — the gate delegates the
        actual spend math to it.
    notification_log_model
        Host's ``NotificationDeliveryLog`` (or equivalent) SQLAlchemy
        model. When provided, a row is inserted on first trip so the
        chassis bell sees it. Pass ``None`` to suppress that side
        effect — useful in tests or contexts where logs would loop.
    redis
        Async ``redis.asyncio.Redis`` client. Used for both the
        SET-NX'd throttle key and the bus publish. ``None`` skips both
        and the helper degrades to "raise + log" only.

    Raises
    ------
    BudgetExceededError
        When ``get_month_to_date_spend >= monthly_budget_usd``. The
        same exception ``assert_within_budget`` would have raised.
    """
    # Cap <= 0 means unlimited — short-circuit before any I/O so the
    # hot path stays free of redundant SQL/Redis round-trips.
    if monthly_budget_usd is None or monthly_budget_usd <= 0:
        return

    cap = _to_decimal(monthly_budget_usd)
    spend = await get_month_to_date_spend(session, UsageModel, company_id)
    if spend < cap:
        # Reuse the soft-warning branch so the 80% log still happens.
        if spend >= Decimal("0.8") * cap:
            logger.warning(
                "usage: company %s at %.0f%% of monthly budget ($%.2f / $%.2f)",
                company_id,
                100 * spend / cap,
                spend,
                cap,
            )
        return

    # Over cap — fire the side effects exactly once per month, then raise.
    await _emit_budget_exhausted_alert(
        session=session,
        company_id=company_id,
        spend=spend,
        cap=cap,
        notification_log_model=notification_log_model,
        redis=redis,
    )
    raise BudgetExceededError(
        f"Company {company_id} has spent ${spend:.2f} of its "
        f"${cap:.2f} monthly AI budget; further "
        "agent calls are blocked until next month or until the "
        "budget is raised."
    )


async def _emit_budget_exhausted_alert(
    *,
    session: Any,
    company_id: str,
    spend: Decimal,
    cap: Decimal,
    notification_log_model: Any | None,
    redis: Any,
) -> None:
    """Idempotent (per company, per month) alert side-effect bundle.

    Separated from the raise so callers that want to alert without
    raising (future ``budget_warning`` at 80%, perhaps) can reuse it.
    """
    import json
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    now = _dt.now(_tz.utc)
    month_key = now.strftime("%Y-%m")
    throttle_key = f"alert_emitted:budget_exhausted:{company_id}:{month_key}"

    # Redis SET NX with end-of-month TTL is the dedupe. When Redis is
    # unavailable we fall through and emit unconditionally — better to
    # double-alert than to silently swallow.
    first_trip = True
    if redis is not None:
        try:
            ttl = await _seconds_until_month_end_utc()
            # ``nx=True`` returns truthy only when the key was newly set.
            result = await redis.set(throttle_key, "1", ex=ttl, nx=True)
            first_trip = bool(result)
        except Exception:  # pragma: no cover - defensive
            logger.warning(
                "budget_exhausted_throttle_redis_failed company=%s",
                company_id,
                exc_info=True,
            )

    if not first_trip:
        logger.info(
            "budget_exhausted_alert_throttled company=%s month=%s",
            company_id,
            month_key,
        )
        return

    payload = {
        "kind": "budget_exhausted",
        "severity": "error",
        "company_id": str(company_id),
        # float() for JSON — Decimal isn't serializable; 4 dp is display-grade.
        "spend_usd": float(round(spend, 4)),
        "cap_usd": float(round(cap, 4)),
        "month": month_key,
        "message": (
            f"AI budget cap reached — ${spend:.2f} of ${cap:.2f} spent. "
            "All AI calls are blocked until the cap is raised or the "
            "month rolls over."
        ),
        "at": now.isoformat(),
    }

    # 1) Notification log row — surfaces in the chassis bell's existing
    #    /api/v1/logs poll. ``recipient_user_id=None`` because the alert
    #    is tenant-wide, not per-user.
    if notification_log_model is not None:
        try:
            row = notification_log_model(
                company_id=uuid.UUID(str(company_id)),
                event_type="budget_exhausted",
                event_payload=payload,
                channel="in_app",
                status="sent",
                sent_at=now,
            )
            session.add(row)
            await session.flush()
        except Exception:  # pragma: no cover - defensive
            logger.warning(
                "budget_exhausted_log_insert_failed company=%s",
                company_id,
                exc_info=True,
            )

    # 2) Bus publish — connected WS subscribers on
    #    org.{X}.alert.budget_exhausted see it instantly.
    if redis is not None:
        channel = f"alert:budget_exhausted:{company_id}"
        try:
            await redis.publish(channel, json.dumps(payload))
        except Exception:  # pragma: no cover - defensive
            logger.warning(
                "budget_exhausted_publish_failed company=%s channel=%s",
                company_id,
                channel,
                exc_info=True,
            )

    logger.error(
        "budget_exhausted_alert_emitted company=%s spend=%.2f cap=%.2f",
        company_id,
        spend,
        cap,
    )
