"""Declared-field hints — exact masking of values a regex can't catch (names)."""

import json

import pytest

from smart_llm.pii.firewall import PiiFirewall, TokenVault

NAME = "Jane Q. Patient"
EMAIL = "jane@example.com"


def test_vault_pre_mints_hints_and_applies_them():
    vault = TokenVault(hints=[(NAME, "NAME")])
    masked = vault.apply_hints(f"patient {NAME} was seen")
    assert NAME not in masked
    assert vault.restore_text(masked) == f"patient {NAME} was seen"


def test_hints_mask_free_text_name_via_firewall():
    fw = PiiFirewall()
    vault = TokenVault(hints=[(NAME, "NAME")])
    masked = fw.mask_text(f"{NAME} emailed {EMAIL}", vault)
    # Name (hint) AND email (detector) both masked, then restored.
    assert NAME not in masked and EMAIL not in masked
    assert fw.restore_obj(masked, vault) == f"{NAME} emailed {EMAIL}"


def test_longest_hint_wins_over_substring():
    # A longer declared value is replaced before a shorter one nested in it.
    vault = TokenVault(hints=[("Jan", "NAME"), ("Jane Smith", "NAME")])
    masked = vault.apply_hints("Jane Smith")
    # The full name is masked as one token, not split by the "Jan" substring.
    assert masked.count("⟦") == 1


def test_no_hints_is_noop():
    vault = TokenVault()
    assert vault.apply_hints("Jane Smith") == "Jane Smith"


@pytest.mark.asyncio
async def test_masking_provider_masks_hint_on_egress():
    from smart_llm.pii.masking_provider import MaskingProvider

    class Fake:
        NAME = "fake"

        def __init__(self):
            self.model_name = "m"
            self.last_usage = {}
            self.seen = None

        async def complete(self, system, user_prompt):
            self.seen = user_prompt
            text = user_prompt if isinstance(user_prompt, str) else json.dumps(user_prompt, ensure_ascii=False)
            return {"content": text}

    inner = Fake()
    mp = MaskingProvider(inner, PiiFirewall(), "enforce", hints=[(NAME, "NAME")])
    out = await mp.complete("sys", f"summarize care for {NAME}")
    assert NAME not in inner.seen  # exact declared name never egressed
    assert NAME in out["content"]  # re-hydrated for the caller


def test_agent_threads_pii_hints():
    from smart_llm import Agent

    agent = Agent(
        name="t",
        provider_type="anthropic",
        system_prompt="s",
        api_key="k",
        pii_policy="enforce",
        pii_hints=[(NAME, "NAME")],
        safety_enabled=False,
    )
    # The hint reached the request vault.
    assert agent._provider._vault.apply_hints(NAME) != NAME
