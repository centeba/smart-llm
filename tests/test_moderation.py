"""Moderation chain: fallthrough, fail-closed/open, LLM + OpenAI backends."""

import asyncio

import pytest

from smart_llm.security.moderation import (
    ChainModerator,
    LLMClassifierModerator,
    ModerationResult,
    ModerationUnavailableError,
    OpenAIModerator,
)


class _Flag:
    backend_name = "flag"

    async def moderate(self, text):
        return ModerationResult(flagged=True, categories=["violence"], backend="flag")


class _Clean:
    backend_name = "clean"

    async def moderate(self, text):
        return ModerationResult(flagged=False, backend="clean")


class _Boom:
    backend_name = "boom"

    async def moderate(self, text):
        raise RuntimeError("backend down")


def test_chain_returns_first_success():
    chain = ChainModerator([_Clean()])
    assert asyncio.run(chain.moderate("hello")).flagged is False


def test_chain_falls_through_to_next():
    chain = ChainModerator([_Boom(), _Flag()])
    res = asyncio.run(chain.moderate("hello"))
    assert res.flagged is True and res.backend == "flag"


def test_chain_fail_closed():
    chain = ChainModerator([_Boom()], fail_open=False)
    with pytest.raises(ModerationUnavailableError):
        asyncio.run(chain.moderate("hello"))


def test_chain_fail_open():
    chain = ChainModerator([_Boom()], fail_open=True)
    res = asyncio.run(chain.moderate("hello"))
    assert res.flagged is False and res.backend == "none"


def test_empty_text_skips_backends():
    chain = ChainModerator([_Boom()])  # would raise if called
    res = asyncio.run(chain.moderate("   "))
    assert res.flagged is False and res.backend == "skip"


# ── LLM-classifier fallback ───────────────────────────────────────────────────


class _FakeProvider:
    def __init__(self, payload):
        self._payload = payload

    async def complete(self, system_prompt, user_prompt):
        return self._payload


def test_llm_classifier_flagged():
    mod = LLMClassifierModerator(
        _FakeProvider({"flagged": True, "categories": ["hate"]})
    )
    res = asyncio.run(mod.moderate("bad text"))
    assert res.flagged is True and "hate" in res.categories


def test_llm_classifier_clean():
    mod = LLMClassifierModerator(_FakeProvider({"flagged": False}))
    assert asyncio.run(mod.moderate("nice text")).flagged is False


# ── OpenAI /moderations backend (monkeypatched client) ────────────────────────


def test_openai_moderator_parses(monkeypatch):
    class _Cats:
        def model_dump(self, by_alias=False):
            return {"violence": True, "hate": False}

    class _Scores:
        def model_dump(self, by_alias=False):
            return {"violence": 0.92, "hate": 0.01}

    class _Result:
        flagged = True
        categories = _Cats()
        category_scores = _Scores()

    class _Resp:
        results = [_Result()]

    class _Mods:
        async def create(self, model, input):
            return _Resp()

    class _Client:
        def __init__(self, api_key):
            self.moderations = _Mods()

    monkeypatch.setattr("openai.AsyncOpenAI", _Client)
    mod = OpenAIModerator(lambda: "sk-test")
    res = asyncio.run(mod.moderate("text"))
    assert res.flagged is True
    assert "violence" in res.categories and "hate" not in res.categories
    assert res.scores["violence"] == 0.92


def test_openai_moderator_no_key_raises():
    mod = OpenAIModerator(lambda: None)
    with pytest.raises(RuntimeError):
        asyncio.run(mod.moderate("text"))
