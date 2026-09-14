"""PR2 wiring — Agent wraps its provider in the firewall when a policy is active."""

import json

import pytest

from smart_llm import Agent
from smart_llm.pii.masking_provider import MaskingProvider


def _agent(pii_policy):
    # Constructing a provider just builds an SDK client (no network call).
    return Agent(
        name="t",
        provider_type="anthropic",
        system_prompt="sys",
        api_key="k",
        pii_policy=pii_policy,
        safety_enabled=False,
    )


def test_provider_wrapped_when_policy_active():
    assert isinstance(_agent("enforce")._provider, MaskingProvider)
    assert isinstance(_agent("detect-only")._provider, MaskingProvider)
    assert isinstance(_agent("strict")._provider, MaskingProvider)


def test_provider_not_wrapped_when_off_or_unset():
    assert not isinstance(_agent(None)._provider, MaskingProvider)
    assert not isinstance(_agent("off")._provider, MaskingProvider)


@pytest.mark.asyncio
async def test_analyze_masks_egress_and_rehydrates(monkeypatch):
    agent = _agent("enforce")
    captured = {}

    async def fake_complete(system, user_prompt):
        captured["system"] = system
        captured["input"] = user_prompt
        text = user_prompt if isinstance(user_prompt, str) else json.dumps(user_prompt, ensure_ascii=False)
        return {"content": text}

    # Replace the inner SDK call — the MaskingProvider wraps this.
    agent._provider._inner.complete = fake_complete

    resp = await agent.analyze("my ssn is 123-45-6789 and card 4111 1111 1111 1111")

    # Inner provider saw only tokens.
    assert "123-45-6789" not in captured["input"]
    assert "4111 1111 1111 1111" not in captured["input"]
    # Caller's response is re-hydrated.
    assert "123-45-6789" in resp.data["content"]


def test_llm_service_default_policy_is_enforce():
    # The host helper flips masking on out-of-the-box when the company hasn't
    # set a policy (company_pii_policy=None → env default 'enforce').
    from smart_llm.api.llm_service import _resolve_pii

    policy, allow_vision = _resolve_pii(None, None)
    assert policy == "enforce"
    assert allow_vision is False


def test_llm_service_agent_override_tightens():
    from smart_llm.api.llm_service import _resolve_pii

    cfg = json.dumps({"pii_masking_policy": "strict", "allow_vision_pii": True})
    policy, allow_vision = _resolve_pii("off", cfg)
    assert policy == "strict"  # agent tightened past company 'off'
    assert allow_vision is True
