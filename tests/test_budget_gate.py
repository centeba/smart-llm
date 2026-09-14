"""Unit tests for :func:`smart_llm.usage.assert_llm_allowed_for_tenant`.

The Phase F tenant gate must:
  1. No-op when cap is 0 (unlimited).
  2. No-op when spend < cap.
  3. On first cap trip: insert a notification log row, publish to the
     Redis channel, raise ``BudgetExceededError``.
  4. On subsequent trips in the same month: raise but skip side effects
     (throttled via SET NX).
  5. Degrade gracefully when redis=None — still raise, just no publish
     and an unthrottled (single-process) log row.

These tests pin the public contract; they're deliberately decoupled
from the host service plumbing (NotificationDeliveryLog, redis client)
via fakes so the gate stays portable across services.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from smart_llm.usage import (
    BudgetExceededError,
    assert_llm_allowed_for_tenant,
)

# Smart-llm's pyproject doesn't set asyncio_mode=auto; opt this module
# in explicitly so async def tests run.
pytestmark = pytest.mark.asyncio


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeAIUsageEvent:
    """Stand-in for the host's AIUsageEvent ORM model."""


class _FakeNotificationLog:
    """Captures the kwargs the gate would insert into the host table."""

    instances: list[_FakeNotificationLog] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakeNotificationLog.instances.append(self)


class _FakeSession:
    """Minimal AsyncSession-shaped fake.

    The gate calls (a) ``get_month_to_date_spend`` which executes a
    SELECT and (b) ``session.add(row)`` then ``session.flush()``. We
    patch the spend value in directly so we don't need to model SQL.
    """

    def __init__(self, spend_usd: float) -> None:
        self._spend = spend_usd
        self.added: list[Any] = []
        self.flush = AsyncMock()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, *_a, **_kw):  # pragma: no cover - patched
        raise RuntimeError("not used — get_month_to_date_spend is monkeypatched")


class _FakeRedis:
    """In-memory SET NX + publish counter."""

    def __init__(self) -> None:
        self._kv: dict[str, str] = {}
        self.publishes: list[tuple[str, str]] = []

    async def set(self, key: str, value: str, *, ex: int = 0, nx: bool = False) -> Any:
        if nx and key in self._kv:
            return None
        self._kv[key] = value
        return True

    async def publish(self, channel: str, payload: str) -> int:
        self.publishes.append((channel, payload))
        return 1


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_fakes():
    _FakeNotificationLog.instances.clear()


@pytest.fixture
def fake_spend(monkeypatch):
    """Pin ``get_month_to_date_spend`` to a controllable value."""

    spend_holder: dict[str, float] = {"value": 0.0}

    async def _stub(_session, _model, _company_id):
        return spend_holder["value"]

    monkeypatch.setattr("smart_llm.usage.get_month_to_date_spend", _stub)
    return spend_holder


async def test_cap_zero_is_unlimited(fake_spend):
    """``monthly_budget_usd=0`` short-circuits — no SQL, no raise."""
    fake_spend["value"] = 9_999.0  # would otherwise blow the cap

    session = _FakeSession(spend_usd=9_999.0)
    redis = _FakeRedis()

    await assert_llm_allowed_for_tenant(
        session,
        company_id="11111111-1111-1111-1111-111111111111",
        UsageModel=_FakeAIUsageEvent,
        monthly_budget_usd=0.0,
        notification_log_model=_FakeNotificationLog,
        redis=redis,
    )
    assert _FakeNotificationLog.instances == []
    assert redis.publishes == []


async def test_under_cap_passes(fake_spend):
    fake_spend["value"] = 3.50
    session = _FakeSession(spend_usd=3.50)
    redis = _FakeRedis()

    await assert_llm_allowed_for_tenant(
        session,
        company_id="11111111-1111-1111-1111-111111111111",
        UsageModel=_FakeAIUsageEvent,
        monthly_budget_usd=10.0,
        notification_log_model=_FakeNotificationLog,
        redis=redis,
    )
    assert _FakeNotificationLog.instances == []
    assert redis.publishes == []


async def test_first_trip_fires_side_effects_and_raises(fake_spend):
    fake_spend["value"] = 12.0
    session = _FakeSession(spend_usd=12.0)
    redis = _FakeRedis()
    cid = "22222222-2222-2222-2222-222222222222"

    with pytest.raises(BudgetExceededError):
        await assert_llm_allowed_for_tenant(
            session,
            company_id=cid,
            UsageModel=_FakeAIUsageEvent,
            monthly_budget_usd=10.0,
            notification_log_model=_FakeNotificationLog,
            redis=redis,
        )

    # Exactly one notification row landed
    assert len(_FakeNotificationLog.instances) == 1
    row = _FakeNotificationLog.instances[0]
    assert row.kwargs["event_type"] == "budget_exhausted"
    assert row.kwargs["channel"] == "in_app"
    assert row.kwargs["status"] == "sent"
    assert str(row.kwargs["company_id"]) == cid

    # And one bus publish on the expected channel
    assert len(redis.publishes) == 1
    channel, _ = redis.publishes[0]
    assert channel == f"alert:budget_exhausted:{cid}"


async def test_second_trip_throttles_side_effects(fake_spend):
    fake_spend["value"] = 12.0
    session = _FakeSession(spend_usd=12.0)
    redis = _FakeRedis()
    cid = "33333333-3333-3333-3333-333333333333"

    # First call lands the alert.
    with pytest.raises(BudgetExceededError):
        await assert_llm_allowed_for_tenant(
            session,
            company_id=cid,
            UsageModel=_FakeAIUsageEvent,
            monthly_budget_usd=10.0,
            notification_log_model=_FakeNotificationLog,
            redis=redis,
        )

    # Second call still raises but no additional row or publish.
    with pytest.raises(BudgetExceededError):
        await assert_llm_allowed_for_tenant(
            session,
            company_id=cid,
            UsageModel=_FakeAIUsageEvent,
            monthly_budget_usd=10.0,
            notification_log_model=_FakeNotificationLog,
            redis=redis,
        )

    assert len(_FakeNotificationLog.instances) == 1
    assert len(redis.publishes) == 1


async def test_no_redis_still_raises(fake_spend):
    """When redis=None we lose throttling + publish, but still raise."""
    fake_spend["value"] = 12.0
    session = _FakeSession(spend_usd=12.0)

    with pytest.raises(BudgetExceededError):
        await assert_llm_allowed_for_tenant(
            session,
            company_id="44444444-4444-4444-4444-444444444444",
            UsageModel=_FakeAIUsageEvent,
            monthly_budget_usd=10.0,
            notification_log_model=_FakeNotificationLog,
            redis=None,
        )
