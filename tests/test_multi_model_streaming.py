"""Multi-model chat streaming — run_agent_streaming routed through Agent.

Covers the seam the multi-model chat feature adds/relies on:
- run_agent_streaming now goes through Agent.analyze_stream, so a streamed turn
  is budget-gated, content-safety-screened, and **usage-recorded** (the raw-SDK
  path it replaced did none of this for openai/anthropic).
- A per-turn ModelOverride selects provider/model without mutating the config.
- usage_ctx wires billing; the row records under the *effective* model.
- Errors and the terminal frame keep the {type: text|error|done} SSE contract.
- smart_llm.catalog derives from PRICING + the OpenRouter meta-entry.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from smart_llm.api.llm_service import (
    ModelOverride,
    UsageRecording,
    run_agent_streaming,
)


async def _async_yield(*items):
    for it in items:
        yield it


def _agent_config(provider="anthropic", model="claude-sonnet-4-6"):
    return SimpleNamespace(
        name="chat",
        provider_type=provider,
        model_name=model,
        model_configuration=None,
        system_prompt="You are helpful.",
    )


def _frames(sse_lines: list[str]) -> list[dict]:
    """Parse ``data: {json}`` SSE lines into payload dicts."""
    out = []
    for line in sse_lines:
        s = line.strip()
        if s.startswith("data: "):
            out.append(json.loads(s[6:]))
    return out


async def _run(cfg, **kwargs) -> list[dict]:
    lines = []
    async for line in run_agent_streaming(cfg, [], "api-key", "hello", **kwargs):
        lines.append(line)
    return _frames(lines)


# ── SSE contract + Agent routing ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_streams_text_then_done_frame():
    with patch("smart_llm.agent.AnthropicProvider") as MockProv:
        inst = MockProv.return_value
        inst.stream = MagicMock(return_value=_async_yield("Hel", "lo"))
        inst.last_usage = {"input_tokens": 3, "output_tokens": 2}
        frames = await _run(_agent_config())
    assert [f["type"] for f in frames] == ["text", "text", "done"]
    assert "".join(f["content"] for f in frames if f["type"] == "text") == "Hello"


@pytest.mark.asyncio
async def test_error_emits_error_then_done():
    def _boom(*a, **k):
        raise RuntimeError("provider exploded")

    with patch("smart_llm.agent.AnthropicProvider") as MockProv:
        inst = MockProv.return_value
        inst.stream = MagicMock(side_effect=_boom)
        inst.last_usage = {"input_tokens": 0, "output_tokens": 0}
        frames = await _run(_agent_config())
    assert [f["type"] for f in frames] == ["error", "done"]
    assert "provider exploded" in frames[0]["content"]


# ── Per-turn model override ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_override_selects_provider_without_mutating_config():
    cfg = _agent_config(provider="anthropic", model="claude-sonnet-4-6")
    with (
        patch("smart_llm.agent.OpenAIProvider") as MockOpenAI,
        patch("smart_llm.agent.AnthropicProvider") as MockAnthropic,
    ):
        MockOpenAI.return_value.stream = MagicMock(return_value=_async_yield("hi"))
        MockOpenAI.return_value.last_usage = {"input_tokens": 1, "output_tokens": 1}
        frames = await _run(cfg, model_override=ModelOverride("openai", "gpt-4o"))
    # Routed to OpenAI, not the bound Anthropic config; DB config untouched.
    MockOpenAI.assert_called_once()
    MockAnthropic.assert_not_called()
    assert cfg.provider_type == "anthropic" and cfg.model_name == "claude-sonnet-4-6"
    assert frames[-1]["type"] == "done"


# ── Usage recording under the effective model (the closed gap) ───────────────


@pytest.mark.asyncio
async def test_usage_recorded_under_effective_model():
    cfg = _agent_config(provider="anthropic")
    captured: dict = {}

    async def _fake_record(session, model, ctx, **kw):
        captured["provider"] = ctx.provider
        captured["model"] = ctx.model
        captured["input_tokens"] = kw.get("input_tokens")
        captured["output_tokens"] = kw.get("output_tokens")

    with (
        patch("smart_llm.agent.OpenAIProvider") as MockOpenAI,
        patch("smart_llm.usage.record_usage", _fake_record),
    ):
        inst = MockOpenAI.return_value
        inst.stream = MagicMock(return_value=_async_yield("a", "b"))
        inst.last_usage = {"input_tokens": 42, "output_tokens": 7}
        usage_ctx = UsageRecording(
            usage_session=MagicMock(),
            usage_model=MagicMock(),
            company_id="c-1",
            monthly_budget_usd=0.0,  # unlimited → no budget round-trip
            agent_id="a-1",
            user_id="u-1",
        )
        await _run(
            cfg,
            model_override=ModelOverride("openai", "gpt-4o"),
            usage_ctx=usage_ctx,
        )
    assert captured["provider"] == "openai"
    assert captured["model"] == "gpt-4o"
    assert captured["input_tokens"] == 42 and captured["output_tokens"] == 7


@pytest.mark.asyncio
async def test_budget_exceeded_surfaces_as_error_frame():
    from smart_llm.usage import BudgetExceededError

    async def _over_budget(*a, **k):
        raise BudgetExceededError("cap reached")

    with (
        patch("smart_llm.agent.AnthropicProvider") as MockProv,
        patch("smart_llm.usage.assert_within_budget", _over_budget),
    ):
        inst = MockProv.return_value
        inst.stream = MagicMock(return_value=_async_yield("should-not-run"))
        inst.last_usage = {"input_tokens": 0, "output_tokens": 0}
        usage_ctx = UsageRecording(
            usage_session=MagicMock(),
            usage_model=MagicMock(),
            company_id="c-1",
            monthly_budget_usd=5.0,  # >0 → budget gate active
        )
        frames = await _run(_agent_config(), usage_ctx=usage_ctx)
    # Gate raised before any token streamed → error, done; no text frames.
    assert [f["type"] for f in frames] == ["error", "done"]
    assert "cap reached" in frames[0]["content"]


# ── Catalog ──────────────────────────────────────────────────────────────────


def test_catalog_derives_from_pricing_and_adds_openrouter():
    from smart_llm import catalog
    from smart_llm.usage import PRICING

    models = catalog.hosted_models()
    slugs = {(m.provider, m.model) for m in models}
    # Every hosted PRICING row is offered.
    for key in PRICING:
        provider, _, model = key.partition(":")
        if provider in catalog.HOSTED_PROVIDERS and model:
            assert (provider, model) in slugs
    # OpenRouter meta-entry present though it has no PRICING row.
    assert ("openrouter", catalog.OPENROUTER_AUTO_MODEL) in slugs


def test_catalog_selectability_and_capabilities():
    from smart_llm import catalog

    assert catalog.is_selectable("openai", "gpt-4o") is True
    assert catalog.is_selectable("openai", "not-a-real-model") is False
    # OpenRouter accepts any slug (gateway routes it).
    assert catalog.is_selectable("openrouter", "meta-llama/llama-3.1-70b") is True
    # gpt-4o is vision-capable per the capability hints.
    gpt4o = next(m for m in catalog.hosted_models() if m.model == "gpt-4o")
    assert "vision" in gpt4o.capabilities


# ── Provider stream() usage capture ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_stream_captures_usage_from_final_chunk():
    from smart_llm.providers.openai import OpenAIProvider

    def _chunk(content=None, usage=None):
        choice = SimpleNamespace(delta=SimpleNamespace(content=content))
        return SimpleNamespace(
            choices=[choice] if content is not None else [], usage=usage
        )

    async def _fake_create(**kwargs):
        # SDK returns an awaitable resolving to an async iterator of chunks.
        assert kwargs.get("stream_options") == {"include_usage": True}

        async def _gen():
            for c in [
                _chunk("Hel"),
                _chunk("lo"),
                _chunk(None, SimpleNamespace(prompt_tokens=11, completion_tokens=4)),
            ]:
                yield c

        return _gen()

    with patch("smart_llm.providers.openai.AsyncOpenAI") as MockSDK:
        MockSDK.return_value.chat.completions.create = _fake_create
        prov = OpenAIProvider(api_key="k", model_name="gpt-4o")
        out = [c async for c in prov.stream("sys", "hi")]
    assert "".join(out) == "Hello"
    assert prov.last_usage == {"input_tokens": 11, "output_tokens": 4}
