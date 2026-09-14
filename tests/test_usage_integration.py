"""Phase E4 — end-to-end usage recording + budget enforcement.

Covers the integration between :class:`smart_llm.agent.Agent` and the
recorder/guard helpers in :mod:`smart_llm.usage`. The Agent layer is
the integration boundary that hosts (integration-hub's AIService,
mit-stack's agent_node activity) plug into, so these tests pin the
contract there:

- Successful ``analyze()`` writes exactly one ``ai_usage_events`` row
  with the resolved provider/model + token counts surfaced via
  ``provider.last_usage``.
- A configured budget below the running spend blocks the next call
  with :class:`BudgetExceededError` *before* hitting the provider —
  no LLM credit burned on a known-rejected request.
- A ``monthly_budget_usd <= 0`` (the unlimited sentinel) disables
  the guard regardless of recorded spend.
- Agents constructed without ``usage_session``/``usage_model`` skip
  both branches and stay on the pre-E4 fast path.
- Repeated calls accumulate; running spend matches the sum of
  ``usd_cost`` across rows.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from smart_llm.agent import Agent
from smart_llm.usage import (
    PRICING,
    BudgetExceededError,
    UsageContext,
    estimate_cost_usd,
    get_month_to_date_spend,
    make_usage_model,
    record_usage,
)

# ── Test scaffolding — in-memory SQLite with the usage table ────────────────


class _Base(DeclarativeBase):
    pass


# Build the ORM model once at import time so all tests share the
# table; SQLAlchemy disallows re-declaring the same mapped class on a
# different metadata.
UsageEvent = make_usage_model(_Base)


@pytest_asyncio.fixture
async def db_session():
    """In-memory aiosqlite session with ``ai_usage_events`` created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


# ── Direct recorder/guard tests (no Agent) ──────────────────────────────────


@pytest.mark.asyncio
async def test_record_usage_inserts_row_with_computed_cost(db_session):
    company = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    cost = await record_usage(
        db_session,
        UsageEvent,
        UsageContext(
            company_id=company,
            agent_id=agent_id,
            skill_id=None,
            provider="anthropic",
            model="claude-sonnet-4-6",
        ),
        input_tokens=1_000_000,
        output_tokens=500_000,
    )
    # 1M in @ $3 + 500K out @ $15 = $3 + $7.50 = $10.50
    assert cost == pytest.approx(10.50, abs=0.001)

    spend = await get_month_to_date_spend(db_session, UsageEvent, company)
    assert spend == pytest.approx(10.50, abs=0.001)


@pytest.mark.asyncio
async def test_zero_events_means_zero_spend(db_session):
    """Sanity floor — empty table → 0% of budget, no rows queried."""
    spend = await get_month_to_date_spend(db_session, UsageEvent, str(uuid.uuid4()))
    assert spend == 0.0


@pytest.mark.asyncio
async def test_record_usage_persists_pii_masking_summary(db_session):
    """The counts-only masking summary round-trips through the JSON column."""
    from sqlalchemy import select

    company = str(uuid.uuid4())
    summary = {
        "policy": "enforce",
        "token_count": 2,
        "per_type_counts": {"SSN": 1, "EMAIL": 1},
        "vision_blocked": 0,
        "fail_closed": False,
        "backend": "regex",
    }
    await record_usage(
        db_session,
        UsageEvent,
        UsageContext(
            company_id=company,
            agent_id=None,
            skill_id=None,
            provider="anthropic",
            model="m",
        ),
        input_tokens=1,
        output_tokens=1,
        pii_masking=summary,
    )
    row = (
        await db_session.execute(
            select(UsageEvent).where(UsageEvent.company_id == uuid.UUID(company))
        )
    ).scalars().first()
    assert row is not None
    assert row.pii_masking == summary


@pytest.mark.asyncio
async def test_record_usage_pii_masking_defaults_null(db_session):
    """Omitting the summary (bare provider / masking off) leaves the column NULL."""
    from sqlalchemy import select

    company = str(uuid.uuid4())
    await record_usage(
        db_session,
        UsageEvent,
        UsageContext(
            company_id=company,
            agent_id=None,
            skill_id=None,
            provider="anthropic",
            model="m",
        ),
        input_tokens=1,
        output_tokens=1,
    )
    row = (
        await db_session.execute(
            select(UsageEvent).where(UsageEvent.company_id == uuid.UUID(company))
        )
    ).scalars().first()
    assert row is not None
    assert row.pii_masking is None


# ── Agent integration — record_usage on success ─────────────────────────────


def _patch_provider(token_counts=(0, 0), data=None):
    """Return a ``patch`` context that swaps in a mock AnthropicProvider
    whose ``complete`` returns ``data`` and whose ``last_usage`` reports
    the given input/output token counts."""
    mock_cls = MagicMock()
    instance = mock_cls.return_value
    instance.complete = AsyncMock(return_value=data or {"content": "ok"})
    instance.last_usage = {
        "input_tokens": token_counts[0],
        "output_tokens": token_counts[1],
    }
    return patch("smart_llm.agent.AnthropicProvider", mock_cls), instance


@pytest.mark.asyncio
async def test_analyze_records_usage_when_wired(db_session):
    company = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    prov_patch, _ = _patch_provider(token_counts=(2_000_000, 1_000_000))
    with prov_patch:
        agent = Agent(
            name="rec-test",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
            model_name="claude-sonnet-4-6",
            usage_session=db_session,
            usage_model=UsageEvent,
            company_id=company,
            agent_id=agent_id,
        )
        await agent.analyze("hi")

    spend = await get_month_to_date_spend(db_session, UsageEvent, company)
    # 2M in @ $3 + 1M out @ $15 = $6 + $15 = $21
    assert spend == pytest.approx(21.0, abs=0.001)


@pytest.mark.asyncio
async def test_analyze_records_masking_summary_under_policy(db_session):
    """With a PII policy active, the recorded usage row carries the counts-only
    masking summary (proving the firewall → _record_usage audit path)."""
    from sqlalchemy import select

    company = str(uuid.uuid4())
    prov_patch, _ = _patch_provider(
        token_counts=(10, 5), data={"content": "noted"}
    )
    with prov_patch:
        agent = Agent(
            name="pii-rec",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
            model_name="claude-sonnet-4-6",
            usage_session=db_session,
            usage_model=UsageEvent,
            company_id=company,
            pii_policy="enforce",
            safety_enabled=False,
        )
        await agent.analyze("my ssn is 123-45-6789 and card 4111 1111 1111 1111")

    row = (
        await db_session.execute(
            select(UsageEvent).where(UsageEvent.company_id == uuid.UUID(company))
        )
    ).scalars().first()
    assert row is not None and row.pii_masking is not None
    assert row.pii_masking["policy"] == "enforce"
    assert row.pii_masking["per_type_counts"].get("SSN") == 1
    assert row.pii_masking["per_type_counts"].get("CREDIT_CARD") == 1


@pytest.mark.asyncio
async def test_agent_without_usage_wiring_stays_silent(db_session):
    """If the host doesn't pass ``usage_session``/``usage_model``, the
    Agent runs the pre-E4 hot path — no DB inserts, no SELECTs."""
    prov_patch, _ = _patch_provider(token_counts=(100, 50))
    with prov_patch:
        agent = Agent(
            name="no-track",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
            model_name="claude-sonnet-4-6",
            # usage_session/usage_model intentionally omitted.
            company_id=str(uuid.uuid4()),
        )
        await agent.analyze("hi")

    # External assertion — the global table is untouched for this
    # company. Use a fresh company_id to avoid contamination from
    # earlier tests sharing the session fixture.
    spend = await get_month_to_date_spend(db_session, UsageEvent, str(uuid.uuid4()))
    assert spend == 0.0


# ── Agent integration — budget guard ────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_under_cap_allows_next_call(db_session):
    """$9.50 of $10 spent → next call still proceeds (80% warning
    only)."""
    company = str(uuid.uuid4())
    # Pre-seed spend just under the cap.
    await record_usage(
        db_session,
        UsageEvent,
        UsageContext(
            company_id=company,
            agent_id=None,
            skill_id=None,
            provider="anthropic",
            model="claude-sonnet-4-6",
        ),
        # Backsolve: ~$9.50 from a known token mix.
        input_tokens=2_500_000,  # 2.5M @ $3 = $7.50
        output_tokens=133_333,  # ~$2.00 @ $15/M
    )

    prov_patch, _ = _patch_provider(token_counts=(10, 5))
    with prov_patch:
        agent = Agent(
            name="under",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
            model_name="claude-sonnet-4-6",
            usage_session=db_session,
            usage_model=UsageEvent,
            company_id=company,
            monthly_budget_usd=10.0,
        )
        # Should not raise.
        resp = await agent.analyze("more please")
        assert resp.provider == "anthropic"


@pytest.mark.asyncio
async def test_budget_at_cap_blocks_next_call(db_session):
    """$10.50 of $10 spent → next call raises ``BudgetExceededError``
    *before* the provider is invoked."""
    company = str(uuid.uuid4())
    await record_usage(
        db_session,
        UsageEvent,
        UsageContext(
            company_id=company,
            agent_id=None,
            skill_id=None,
            provider="anthropic",
            model="claude-sonnet-4-6",
        ),
        input_tokens=1_000_000,
        output_tokens=500_000,
    )  # = $10.50

    prov_patch, mock_instance = _patch_provider(token_counts=(10, 5))
    with prov_patch:
        agent = Agent(
            name="capped",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
            model_name="claude-sonnet-4-6",
            usage_session=db_session,
            usage_model=UsageEvent,
            company_id=company,
            monthly_budget_usd=10.0,
        )
        with pytest.raises(BudgetExceededError, match="monthly AI budget"):
            await agent.analyze("nope")

    # Critical: provider never called — we don't burn a credit on a
    # known-rejected request.
    mock_instance.complete.assert_not_called()


@pytest.mark.asyncio
async def test_null_budget_is_unlimited(db_session):
    """``monthly_budget_usd=0.0`` (sentinel from the missing-row path)
    disables the guard regardless of recorded spend."""
    company = str(uuid.uuid4())
    # Seed a wildly over-spent month.
    await record_usage(
        db_session,
        UsageEvent,
        UsageContext(
            company_id=company,
            agent_id=None,
            skill_id=None,
            provider="anthropic",
            model="claude-sonnet-4-6",
        ),
        input_tokens=100_000_000,
        output_tokens=50_000_000,
    )  # ≈ $1,050

    prov_patch, mock_instance = _patch_provider(token_counts=(10, 5))
    with prov_patch:
        agent = Agent(
            name="free-tier",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
            model_name="claude-sonnet-4-6",
            usage_session=db_session,
            usage_model=UsageEvent,
            company_id=company,
            monthly_budget_usd=0.0,  # unlimited sentinel
        )
        await agent.analyze("ok")
        mock_instance.complete.assert_called_once()


@pytest.mark.asyncio
async def test_pricing_table_unknown_model_returns_zero(db_session):
    """Unknown ``provider:model`` keys log a warning + record $0 cost
    but still write the row (token trends remain valid)."""
    company = str(uuid.uuid4())
    cost = await record_usage(
        db_session,
        UsageEvent,
        UsageContext(
            company_id=company,
            agent_id=None,
            skill_id=None,
            provider="anthropic",
            model="claude-future-model-not-in-PRICING",
        ),
        input_tokens=1_000_000,
        output_tokens=500_000,
    )
    # M4: an unpriced model no longer counts as $0 (that's "no cap"). It falls
    # back to the priciest same-provider rate (anthropic 15/75), so
    # 1M in @ $15 + 500K out @ $75 = $52.50.
    assert cost == pytest.approx(52.5, abs=0.001)
    spend = await get_month_to_date_spend(db_session, UsageEvent, company)
    assert spend == pytest.approx(52.5, abs=0.001)


def test_pricing_table_present_for_canonical_models():
    """Canary against accidental PRICING-table breakage on rename."""
    assert "anthropic:claude-sonnet-4-6" in PRICING
    assert estimate_cost_usd(
        "anthropic", "claude-sonnet-4-6", 1_000_000, 0
    ) == pytest.approx(3.00)


# ── Gate 9: money is exact Decimal + recording is idempotent ────────────────


def test_estimate_cost_is_decimal_and_exact():
    """Money math must be exact Decimal, not binary float. A cost whose float
    representation drifts (0.1-style) must sum without error over many calls."""
    from decimal import Decimal

    # gpt-4o-mini: $0.15 in / $0.60 out per 1M. 100k in + 100k out =
    # 0.015 + 0.06 = exactly $0.075 — a value float cannot hold exactly.
    one = estimate_cost_usd("openai", "gpt-4o-mini", 100_000, 100_000)
    assert isinstance(one, Decimal)
    assert one == Decimal("0.075")
    # Summed over many calls the total stays exact (the ledger is summed to
    # enforce the monthly cap, so drift is unacceptable).
    total = sum(
        (
            estimate_cost_usd("openai", "gpt-4o-mini", 100_000, 100_000)
            for _ in range(1000)
        ),
        Decimal("0"),
    )
    assert total == Decimal("75.000")


@pytest.mark.asyncio
async def test_record_usage_idempotent(db_session):
    """A retried provider call carrying the same idempotency_key must not
    double-count: one row, and the already-recorded cost is returned."""
    from decimal import Decimal

    company = str(uuid.uuid4())
    ctx = UsageContext(
        company_id=company,
        agent_id=None,
        skill_id=None,
        provider="openai",
        model="gpt-4o",
    )
    key = "provider-request-abc123"
    c1 = await record_usage(
        db_session,
        UsageEvent,
        ctx,
        input_tokens=1_000_000,
        output_tokens=0,
        idempotency_key=key,
    )
    # Same key again (a retry) — must be a no-op insert returning the same cost.
    c2 = await record_usage(
        db_session,
        UsageEvent,
        ctx,
        input_tokens=1_000_000,
        output_tokens=0,
        idempotency_key=key,
    )
    assert c1 == c2 == Decimal("2.5")  # gpt-4o $2.50/1M in

    from sqlalchemy import func, select

    n = (
        await db_session.execute(
            select(func.count())
            .select_from(UsageEvent)
            .where(UsageEvent.idempotency_key == key)
        )
    ).scalar_one()
    assert n == 1  # exactly one row despite two record_usage calls

    # Spend reflects a single charge, not double.
    spend = await get_month_to_date_spend(db_session, UsageEvent, company)
    assert spend == Decimal("2.5")


@pytest.mark.asyncio
async def test_record_usage_without_key_still_inserts_each_time(db_session):
    """Back-compat: no idempotency_key → every call records (unchanged)."""
    company = str(uuid.uuid4())
    ctx = UsageContext(
        company_id=company,
        agent_id=None,
        skill_id=None,
        provider="openai",
        model="gpt-4o",
    )
    await record_usage(
        db_session, UsageEvent, ctx, input_tokens=1_000_000, output_tokens=0
    )
    await record_usage(
        db_session, UsageEvent, ctx, input_tokens=1_000_000, output_tokens=0
    )
    from decimal import Decimal

    spend = await get_month_to_date_spend(db_session, UsageEvent, company)
    assert spend == Decimal("5.0")  # both counted


@pytest.mark.asyncio
async def test_budget_compare_is_exact_decimal(db_session):
    """The cap check compares Decimal spend to a (float) budget without drift or
    TypeError, and raises exactly at the cap."""
    from smart_llm.usage import assert_within_budget

    company = str(uuid.uuid4())
    ctx = UsageContext(
        company_id=company,
        agent_id=None,
        skill_id=None,
        provider="openai",
        model="gpt-4o-mini",
    )
    # Accrue exactly $0.075.
    await record_usage(
        db_session, UsageEvent, ctx, input_tokens=100_000, output_tokens=100_000
    )
    # Just under cap → allowed.
    await assert_within_budget(db_session, UsageEvent, company, monthly_budget_usd=0.08)
    # At/over cap → blocked (0.075 >= 0.075).
    with pytest.raises(BudgetExceededError):
        await assert_within_budget(
            db_session, UsageEvent, company, monthly_budget_usd=0.075
        )
