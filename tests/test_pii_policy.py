"""Policy resolution — most-restrictive wins, env default, vision gating."""

import pytest

from smart_llm.pii import policy


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("SMART_LLM_PII_DEFAULT_POLICY", raising=False)
    yield


def test_default_is_enforce_when_unset():
    assert policy.default_policy() == "enforce"
    assert policy.resolve_pii_policy(None, None) == "enforce"


def test_env_default_override(monkeypatch):
    monkeypatch.setenv("SMART_LLM_PII_DEFAULT_POLICY", "detect-only")
    assert policy.resolve_pii_policy(None, None) == "detect-only"


def test_invalid_env_falls_back_to_enforce(monkeypatch):
    monkeypatch.setenv("SMART_LLM_PII_DEFAULT_POLICY", "banana")
    assert policy.default_policy() == "enforce"


def test_company_policy_used_when_set():
    assert policy.resolve_pii_policy("off", None) == "off"
    assert policy.resolve_pii_policy("strict", None) == "strict"


def test_agent_may_tighten_but_not_loosen():
    # Company off, agent enforces → enforce.
    assert policy.resolve_pii_policy("off", {"pii_masking_policy": "enforce"}) == "enforce"
    # Company strict, agent tries to relax → stays strict.
    assert policy.resolve_pii_policy("strict", {"pii_masking_policy": "off"}) == "strict"
    # Equal → unchanged.
    assert policy.resolve_pii_policy("enforce", {"pii_masking_policy": "enforce"}) == "enforce"


def test_unknown_agent_override_ignored():
    assert policy.resolve_pii_policy("enforce", {"pii_masking_policy": "nope"}) == "enforce"
    assert policy.resolve_pii_policy("enforce", {}) == "enforce"


def test_is_active():
    assert not policy.is_active("off")
    assert policy.is_active("detect-only")
    assert policy.is_active("enforce")
    assert policy.is_active("strict")
    assert not policy.is_active("garbage")  # unrecognised → treated as inactive


def test_allow_vision_matrix():
    assert policy.allow_vision("off")
    assert policy.allow_vision("detect-only")
    assert not policy.allow_vision("enforce")
    assert policy.allow_vision("enforce", allow_vision_pii=True)
    assert not policy.allow_vision("strict")
    assert not policy.allow_vision("strict", allow_vision_pii=True)
