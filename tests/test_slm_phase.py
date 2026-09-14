"""Phase SLM tests — env-driven max_tokens + native multi-turn.

Covers the surface introduced by the SLM1+SLM2 PR:

  * AnthropicProvider reads ``SMART_LLM_MAX_TOKENS`` env at construct
    time and exposes it as ``self.max_tokens``.
  * Explicit ``max_tokens=`` kwarg wins over the env var.
  * Invalid env values fall back to the 4096 default with a log
    warning (no crash).
  * ``Agent.analyze(messages=[...])`` passes the message array
    straight through to the provider — no flattening.
  * ``Agent.analyze(input_text='...', messages=[...])`` appends the
    new user turn after the existing history.
  * ``Conversation.send`` accumulates user/assistant turns and
    surfaces the assistant text from ``LLMResponse.data['content']``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# ─── SLM1: max_tokens env var ────────────────────────────────────────────────


def _build_anthropic_provider(**kwargs):
    """Construct AnthropicProvider with the AsyncAnthropic client mocked
    so no network call escapes the tests."""
    from smart_llm.providers.anthropic import AnthropicProvider

    with patch("smart_llm.providers.anthropic.AsyncAnthropic"):
        return AnthropicProvider(api_key="test", **kwargs)


def test_anthropic_max_tokens_default_when_no_env(monkeypatch):
    monkeypatch.delenv("SMART_LLM_MAX_TOKENS", raising=False)
    provider = _build_anthropic_provider()
    assert provider.max_tokens == 4096


def test_anthropic_max_tokens_reads_env(monkeypatch):
    monkeypatch.setenv("SMART_LLM_MAX_TOKENS", "12345")
    provider = _build_anthropic_provider()
    assert provider.max_tokens == 12345


def test_anthropic_max_tokens_explicit_wins_over_env(monkeypatch):
    monkeypatch.setenv("SMART_LLM_MAX_TOKENS", "12345")
    provider = _build_anthropic_provider(max_tokens=512)
    assert provider.max_tokens == 512


def test_anthropic_max_tokens_invalid_env_falls_back_with_warning(
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("SMART_LLM_MAX_TOKENS", "not-a-number")
    with caplog.at_level("WARNING"):
        provider = _build_anthropic_provider()
    assert provider.max_tokens == 4096
    assert any("SMART_LLM_MAX_TOKENS" in rec.message for rec in caplog.records)


# ─── SLM2: native multi-turn ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_analyze_messages_passes_through_to_provider():
    """Pure multi-turn — ``messages`` only, no ``input_text``. The
    provider receives the message list verbatim."""
    from smart_llm.agent import Agent

    history = [
        {"role": "user", "content": "First turn from user."},
        {"role": "assistant", "content": "First assistant reply."},
        {"role": "user", "content": "Follow-up question."},
    ]

    with patch("smart_llm.agent.AnthropicProvider") as MockProv:
        instance = MockProv.return_value
        instance.complete = AsyncMock(return_value={"content": "A reply."})
        instance.last_usage = {"input_tokens": 10, "output_tokens": 5}

        agent = Agent(
            name="multi_turn_agent",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
        )
        response = await agent.analyze(messages=history)

    instance.complete.assert_awaited_once()
    args, _ = instance.complete.call_args
    # Args: (system_prompt, provider_input)
    assert args[0] == "sys"
    # Pass-through — same list (defensive copy ok), same content.
    assert args[1] == history
    assert response.data == {"content": "A reply."}


@pytest.mark.asyncio
async def test_agent_analyze_messages_plus_input_appends_new_turn():
    """``messages`` + ``input_text`` — the new user turn is appended
    after the existing history."""
    from smart_llm.agent import Agent

    history = [
        {"role": "user", "content": "Hi."},
        {"role": "assistant", "content": "Hello!"},
    ]

    with patch("smart_llm.agent.AnthropicProvider") as MockProv:
        instance = MockProv.return_value
        instance.complete = AsyncMock(return_value={"content": "OK."})
        instance.last_usage = {"input_tokens": 0, "output_tokens": 0}

        agent = Agent(
            name="agent",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
        )
        await agent.analyze(input_text="Latest question.", messages=history)

    args, _ = instance.complete.call_args
    sent = args[1]
    assert sent[:2] == history
    assert sent[2] == {"role": "user", "content": "Latest question."}


@pytest.mark.asyncio
async def test_agent_analyze_string_only_unchanged_legacy_path():
    """Backwards-compat — single-string callers must still get the
    pre-SLM2 ``Context: …\\n\\nInput: …`` wrap when context is set,
    or the bare string when it isn't."""
    from smart_llm.agent import Agent

    with patch("smart_llm.agent.AnthropicProvider") as MockProv:
        instance = MockProv.return_value
        instance.complete = AsyncMock(return_value={"content": "OK."})
        instance.last_usage = {"input_tokens": 0, "output_tokens": 0}

        agent = Agent(
            name="agent",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
        )
        await agent.analyze("plain input", context="ctx")

    args, _ = instance.complete.call_args
    assert args[1] == "Context: ctx\n\nInput: plain input"


@pytest.mark.asyncio
async def test_conversation_accumulates_turns():
    """``Conversation.send`` appends user + assistant turns and feeds
    the growing history to subsequent calls."""
    from smart_llm.agent import Agent
    from smart_llm.conversation import Conversation

    with patch("smart_llm.agent.AnthropicProvider") as MockProv:
        instance = MockProv.return_value
        instance.last_usage = {"input_tokens": 0, "output_tokens": 0}
        # Two distinct replies — one per send().
        instance.complete = AsyncMock(
            side_effect=[
                {"content": "Nice to meet you, Alice."},
                {"content": "Your name is Alice."},
            ]
        )

        agent = Agent(
            name="chat",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
        )
        conv = Conversation(agent)

        first = await conv.send("My name is Alice.")
        second = await conv.send("What's my name?")

    assert first == "Nice to meet you, Alice."
    assert second == "Your name is Alice."

    # Second provider call should have seen the full prior history
    # (user + assistant from turn 1 + new user from turn 2).
    assert instance.complete.await_count == 2
    second_call_args = instance.complete.await_args_list[1].args
    sent = second_call_args[1]
    assert sent == [
        {"role": "user", "content": "My name is Alice."},
        {"role": "assistant", "content": "Nice to meet you, Alice."},
        {"role": "user", "content": "What's my name?"},
    ]

    # Local history mirrors what was sent + the final assistant turn.
    assert conv.messages[-1] == {
        "role": "assistant",
        "content": "Your name is Alice.",
    }


def test_conversation_extract_text_falls_back_to_json():
    """When the provider returns shape unrelated to ``content``, the
    fallback dumps JSON so the caller still sees something useful."""
    from smart_llm.base import LLMResponse
    from smart_llm.conversation import Conversation

    response = LLMResponse(
        data={"unexpected_key": "value"},
        provider="anthropic",
        metadata={},
    )
    text = Conversation._extract_text(response)
    assert "unexpected_key" in text
    assert "value" in text


def test_conversation_reset_clears_history():
    from smart_llm.conversation import Conversation

    # Seed with a fake agent — reset() doesn't touch it.
    conv = Conversation.__new__(Conversation)
    conv.agent = None  # type: ignore[assignment]
    conv.messages = [
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": "y"},
    ]
    conv.reset()
    assert conv.messages == []
