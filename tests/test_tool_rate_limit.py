"""Tool-invocation rate limiting — token bucket + policy-gate integration."""

import pytest
from pydantic import BaseModel

from smart_llm.security.rate_limit import (
    RateLimit,
    TokenBucketRateLimiter,
    make_tool_rate_limiter,
)
from smart_llm.security.tool_policy import AgentRunContext, ToolPolicyGate


class _Args(BaseModel):
    pass


class _ReadTool:
    @classmethod
    def effective_risk(cls):
        return "read"


def test_token_bucket_allows_then_denies():
    rl = TokenBucketRateLimiter(RateLimit(capacity=2, refill_per_sec=0))
    assert rl.check("k") is True
    assert rl.check("k") is True
    assert rl.check("k") is False  # bucket empty, no refill


def test_token_bucket_keys_are_independent():
    rl = TokenBucketRateLimiter(RateLimit(capacity=1, refill_per_sec=0))
    assert rl.check("a") is True
    assert rl.check("b") is True  # separate key, own bucket
    assert rl.check("a") is False


def test_token_bucket_refills(monkeypatch):
    import smart_llm.security.rate_limit as mod

    t = {"now": 100.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: t["now"])
    rl = TokenBucketRateLimiter(RateLimit(capacity=1, refill_per_sec=1.0))
    assert rl.check("k") is True
    assert rl.check("k") is False
    t["now"] += 1.0  # one second → one token back
    assert rl.check("k") is True


@pytest.mark.asyncio
async def test_gate_denies_over_rate_limit():
    # capacity 1, no refill: the first allowed call passes, the second is denied.
    limiter = make_tool_rate_limiter(RateLimit(capacity=1, refill_per_sec=0))
    ctx = AgentRunContext(
        agent_id="ag",
        acting_company_id="co",
        tool_modes={"ReadThing": "allow"},
        rate_limiter=limiter,
    )
    gate = ToolPolicyGate(ctx)

    d1 = await gate.evaluate(tool_name="ReadThing", tool_cls=_ReadTool, validated_args=_Args())
    assert d1.allowed
    d2 = await gate.evaluate(tool_name="ReadThing", tool_cls=_ReadTool, validated_args=_Args())
    assert not d2.allowed
    assert d2.decision == "deny"
    assert d2.reason == "rate limit exceeded"
    assert d2.audit["reason"] == "rate limit exceeded"


@pytest.mark.asyncio
async def test_denied_call_does_not_consume_budget():
    # A tool that is denied by policy shouldn't consume the rate budget, so a
    # later allowed tool still has its full allowance.
    limiter = make_tool_rate_limiter(RateLimit(capacity=1, refill_per_sec=0))
    ctx = AgentRunContext(
        agent_id="ag",
        acting_company_id="co",
        tool_modes={"ReadThing": "allow"},  # DeniedThing absent → denied
        rate_limiter=limiter,
    )
    gate = ToolPolicyGate(ctx)

    denied = await gate.evaluate(
        tool_name="DeniedThing", tool_cls=_ReadTool, validated_args=_Args()
    )
    assert not denied.allowed  # not in allow-list
    # The allowed tool still gets its one token.
    ok = await gate.evaluate(tool_name="ReadThing", tool_cls=_ReadTool, validated_args=_Args())
    assert ok.allowed


@pytest.mark.asyncio
async def test_limiter_failure_fails_open():
    async def _boom(agent_id, company_id, tool_name):
        raise RuntimeError("limiter down")

    ctx = AgentRunContext(
        agent_id="ag",
        acting_company_id="co",
        tool_modes={"ReadThing": "allow"},
        rate_limiter=_boom,
    )
    gate = ToolPolicyGate(ctx)
    d = await gate.evaluate(tool_name="ReadThing", tool_cls=_ReadTool, validated_args=_Args())
    assert d.allowed  # availability: a limiter blip does not deny legitimate calls
