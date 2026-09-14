"""OpenRouter integration — cost capture + per-tenant provider policy."""

import types

import pytest

from smart_llm.provider_policy import (
    TenantAIPolicy,
    resolve_agent_provider,
    resolve_provider,
    split_openrouter_slug,
)
from smart_llm.providers.openrouter import OPENROUTER_BASE_URL, OpenRouterProvider

# ── Provider wiring ──────────────────────────────────────────────────────────


def test_openrouter_points_at_gateway_and_requests_cost():
    p = OpenRouterProvider(
        api_key="sk-or-test", model_name="anthropic/claude-sonnet-4.5"
    )
    assert str(p.client.base_url).rstrip("/") == OPENROUTER_BASE_URL
    # Cost accounting is requested on every call.
    assert p._extra_create_kwargs() == {"extra_body": {"usage": {"include": True}}}


def test_capture_provider_cost_reads_usage_cost_object():
    p = OpenRouterProvider(api_key="sk-or-test")
    resp = types.SimpleNamespace(usage=types.SimpleNamespace(cost=0.0123))
    p._capture_provider_cost(resp)
    assert p.last_usage["cost_usd"] == pytest.approx(0.0123)


def test_capture_provider_cost_reads_usage_cost_dict_and_survives_missing():
    p = OpenRouterProvider(api_key="sk-or-test")
    p._capture_provider_cost(types.SimpleNamespace(usage={"cost": 0.5}))
    assert p.last_usage["cost_usd"] == pytest.approx(0.5)
    # No usage / no cost → no crash, no key added.
    p2 = OpenRouterProvider(api_key="sk-or-test")
    p2._capture_provider_cost(types.SimpleNamespace(usage=None))
    assert "cost_usd" not in p2.last_usage


def test_direct_openai_provider_unchanged_by_the_hooks():
    from smart_llm.providers.openai import OpenAIProvider

    op = OpenAIProvider(api_key="sk-test")
    assert op._extra_create_kwargs() == {}  # no gateway cost accounting
    assert op._capture_provider_cost(object()) is None  # no-op


# ── record_usage honours an explicit gateway cost ────────────────────────────


@pytest.mark.asyncio
async def test_record_usage_prefers_explicit_cost_over_pricing_table():
    from smart_llm.usage import UsageContext, record_usage

    inserted = {}

    class _Row:
        def __init__(self, **kw):
            inserted.update(kw)

    class _Session:
        def add(self, row):
            pass

        async def flush(self):
            pass

    ctx = UsageContext(
        company_id="11111111-1111-1111-1111-111111111111",
        agent_id=None,
        skill_id=None,
        provider="openrouter",
        model="anthropic/claude-sonnet-4.5",  # not in PRICING → would hit fallback
    )
    cost = await record_usage(
        _Session(),
        _Row,
        ctx,
        input_tokens=1000,
        output_tokens=1000,
        cost_usd=0.0042,
    )
    # cost is now an exact Decimal (readiness gate 9); compare via float.
    assert float(cost) == pytest.approx(0.0042)
    assert float(inserted["usd_cost"]) == pytest.approx(0.0042)


@pytest.mark.asyncio
async def test_record_usage_falls_back_to_pricing_when_no_cost():
    from smart_llm.usage import UsageContext, estimate_cost_usd, record_usage

    class _Row:
        def __init__(self, **kw):
            self.usd_cost = kw["usd_cost"]

    class _Session:
        def add(self, row):
            pass

        async def flush(self):
            pass

    ctx = UsageContext(
        company_id="11111111-1111-1111-1111-111111111111",
        agent_id=None,
        skill_id=None,
        provider="openai",
        model="gpt-4o",
    )
    cost = await record_usage(
        _Session(), _Row, ctx, input_tokens=1_000_000, output_tokens=0
    )
    assert cost == pytest.approx(estimate_cost_usd("openai", "gpt-4o", 1_000_000, 0))
    assert cost == pytest.approx(2.50)  # gpt-4o input rate


# ── Per-tenant provider policy ───────────────────────────────────────────────


def test_slug_split():
    assert split_openrouter_slug("anthropic/claude-sonnet-4.5") == (
        "anthropic",
        "claude-sonnet-4.5",
    )
    assert split_openrouter_slug("google/gemini-3.1-pro") == (
        "gemini",
        "gemini-3.1-pro",
    )
    assert split_openrouter_slug("openrouter/auto") == (None, None)  # meta-router
    assert split_openrouter_slug("gpt-4o") == (None, None)  # bare, no vendor


def test_non_gateway_config_passes_through():
    pol = TenantAIPolicy(allow_gateway=False)
    assert resolve_provider("anthropic", "claude-opus-4-6", pol) == (
        "anthropic",
        "claude-opus-4-6",
    )


def test_gateway_allowed_stays_on_gateway():
    pol = TenantAIPolicy(allow_gateway=True)
    assert resolve_provider("openrouter", "anthropic/claude-sonnet-4.5", pol) == (
        "openrouter",
        "anthropic/claude-sonnet-4.5",
    )


def test_gateway_denied_downgrades_to_direct_vendor():
    pol = TenantAIPolicy(allow_gateway=False)
    assert resolve_provider("openrouter", "anthropic/claude-sonnet-4.5", pol) == (
        "anthropic",
        "claude-sonnet-4.5",
    )
    assert resolve_provider("openrouter", "openai/gpt-5.1", pol) == (
        "openai",
        "gpt-5.1",
    )


def test_gateway_denied_meta_router_uses_fallback():
    pol = TenantAIPolicy(
        allow_gateway=False,
        fallback_provider="anthropic",
        fallback_model="claude-sonnet-4-6",
    )
    assert resolve_provider("openrouter", "openrouter/auto", pol) == (
        "anthropic",
        "claude-sonnet-4-6",
    )


# ── Host-facing resolve_agent_provider (the wiring one-liner) ─────────────────


def test_resolve_agent_provider_default_keeps_gateway():
    # No config → allow_gateway defaults True → gateway kept.
    assert resolve_agent_provider(
        "openrouter", "anthropic/claude-sonnet-4.5", None
    ) == (
        "openrouter",
        "anthropic/claude-sonnet-4.5",
    )


def test_resolve_agent_provider_per_agent_flag_from_json_string():
    # model_configuration is a JSON *string* (as stored on AIAgentConfig).
    cfg = '{"base_url": null, "allow_gateway": false}'
    assert resolve_agent_provider("openrouter", "anthropic/claude-sonnet-4.5", cfg) == (
        "anthropic",
        "claude-sonnet-4.5",
    )


def test_resolve_agent_provider_company_flag_overrides():
    # Per-agent allows, but the company policy forbids → downgrade.
    assert resolve_agent_provider(
        "openrouter",
        "openai/gpt-5.1",
        '{"allow_gateway": true}',
        company_allows_gateway=False,
    ) == ("openai", "gpt-5.1")


def test_resolve_agent_provider_malformed_config_is_safe():
    # Garbage config → treated as empty → default allow (no crash).
    assert resolve_agent_provider("openrouter", "openai/gpt-5.1", "{not json") == (
        "openrouter",
        "openai/gpt-5.1",
    )


def test_resolve_agent_provider_direct_unchanged():
    assert resolve_agent_provider(
        "anthropic", "claude-opus-4-6", '{"allow_gateway": false}'
    ) == (
        "anthropic",
        "claude-opus-4-6",
    )
