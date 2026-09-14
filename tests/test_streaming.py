"""Phase E3 tests — Agent.analyze_stream and provider.stream contracts.

Coverage:
- ``Agent.analyze_stream`` yields each delta from the provider verbatim
  (no buffering / no premature termination).
- The context-wrap (``Context: <ctx>\\n\\nInput: <text>``) is applied to
  the single-turn path, same as ``analyze``.
- The SLM2 ``messages=`` kwarg path also works for streaming — list is
  passed through to the provider.
- Provider missing ``stream()`` → ``NotImplementedError``.
- Output tools are NOT applied to the stream path (the docstring
  promises raw chunks).
- Anthropic ``stream()`` uses ``self.max_tokens`` from the SLM1 env
  knob, not the old hardcoded 4096.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────


async def _async_yield(*items):
    """Helper: build an async iterator from a list of items so we can
    use it as a ``stream()`` return value in tests."""
    for it in items:
        yield it


# ── Agent.analyze_stream ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_stream_yields_deltas_verbatim():
    """The Agent layer must not buffer or transform the provider's
    delta stream — chunks come through one-by-one."""
    from smart_llm.agent import Agent

    with patch("smart_llm.agent.AnthropicProvider") as MockProv:
        instance = MockProv.return_value
        instance.stream = MagicMock(return_value=_async_yield("Hel", "lo, ", "world!"))

        agent = Agent(
            name="stream-test",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
        )

        chunks = []
        async for c in agent.analyze_stream("hi"):
            chunks.append(c)

    assert chunks == ["Hel", "lo, ", "world!"]


@pytest.mark.asyncio
async def test_analyze_stream_applies_context_wrap_on_single_turn():
    """Single-turn callers get the same ``Context: ...\\n\\nInput: ...``
    shape as ``analyze``. Streaming doesn't change the prompt
    contract."""
    from smart_llm.agent import Agent

    captured: dict = {}

    def _capture_stream(system_prompt, user_prompt):
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        return _async_yield("ok")

    with patch("smart_llm.agent.AnthropicProvider") as MockProv:
        instance = MockProv.return_value
        instance.stream = MagicMock(side_effect=_capture_stream)

        agent = Agent(
            name="agent",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
        )

        async for _ in agent.analyze_stream("the question", context="the ctx"):
            pass

    assert captured["system"] == "sys"
    assert captured["user"] == "Context: the ctx\n\nInput: the question"


@pytest.mark.asyncio
async def test_analyze_stream_messages_kwarg_passes_through():
    """SLM2 multi-turn stream — list of messages goes straight to the
    provider; no flattening into a single user_prompt string."""
    from smart_llm.agent import Agent

    captured: dict = {}

    def _capture_stream(system_prompt, user_prompt):
        captured["user_prompt"] = user_prompt
        return _async_yield("hi")

    with patch("smart_llm.agent.AnthropicProvider") as MockProv:
        instance = MockProv.return_value
        instance.stream = MagicMock(side_effect=_capture_stream)

        agent = Agent(
            name="agent",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
        )

        history = [
            {"role": "user", "content": "First."},
            {"role": "assistant", "content": "Hi."},
            {"role": "user", "content": "Follow-up."},
        ]
        async for _ in agent.analyze_stream(messages=history):
            pass

    # Pure multi-turn — same list, not flattened.
    assert captured["user_prompt"] == history


@pytest.mark.asyncio
async def test_analyze_stream_appends_input_after_messages():
    """messages + input_text — new user turn appended after the history,
    same rule as ``analyze``."""
    from smart_llm.agent import Agent

    captured: dict = {}

    def _capture_stream(system_prompt, user_prompt):
        captured["user_prompt"] = user_prompt
        return _async_yield("ok")

    with patch("smart_llm.agent.AnthropicProvider") as MockProv:
        instance = MockProv.return_value
        instance.stream = MagicMock(side_effect=_capture_stream)

        agent = Agent(
            name="agent",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
        )

        history = [
            {"role": "user", "content": "Earlier"},
            {"role": "assistant", "content": "Reply"},
        ]
        async for _ in agent.analyze_stream("Latest question", messages=history):
            pass

    sent = captured["user_prompt"]
    assert sent[:2] == history
    assert sent[2] == {"role": "user", "content": "Latest question"}


@pytest.mark.asyncio
async def test_analyze_stream_raises_when_provider_has_no_stream():
    """If the host wires a custom provider without ``stream()``, the
    Agent surface fails fast — not silently degrade to ``analyze``."""
    from smart_llm.agent import Agent

    with patch("smart_llm.agent.AnthropicProvider") as MockProv:
        instance = MockProv.return_value
        # Strip the ``stream`` attribute so hasattr returns False.
        # MagicMock auto-creates attrs on access; spec is the trick.
        del instance.stream

        agent = Agent(
            name="agent",
            provider_type="anthropic",
            system_prompt="sys",
            api_key="key",
        )
        with pytest.raises(NotImplementedError, match="no stream"):
            async for _ in agent.analyze_stream("hi"):
                pass


# ── Anthropic provider stream — SLM1 max_tokens path ─────────────────────────


@pytest.mark.asyncio
async def test_anthropic_stream_uses_self_max_tokens(monkeypatch):
    """Phase SLM1 made ``max_tokens`` env-driven on the Anthropic
    provider. Make sure the ``stream()`` path honours ``self.max_tokens``
    just like ``complete()`` and ``call_with_tools()`` do."""
    monkeypatch.setenv("SMART_LLM_MAX_TOKENS", "8000")
    captured: dict = {}

    # Build the mock stream context manager that the SDK returns.
    class _StreamCtx:
        async def __aenter__(self):
            self.text_stream = _async_yield("ok")
            return self

        async def __aexit__(self, *exc):
            return False

    def _capture_messages_stream(**kwargs):
        captured.update(kwargs)
        return _StreamCtx()

    with patch("smart_llm.providers.anthropic.AsyncAnthropic") as MockSDK:
        mock_client = MockSDK.return_value
        mock_client.messages.stream = _capture_messages_stream

        # Construct after monkeypatch so ``_resolve_max_tokens``
        # picks up the env var.
        from smart_llm.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider(api_key="key")
        assert provider.max_tokens == 8000  # SLM1 sanity

        async for _ in provider.stream("sys", "hi"):
            pass

    assert captured["max_tokens"] == 8000
    # Verify single-string path wraps as a user message.
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
