"""Conversation-window managers — sliding window, summarizing, integration."""

import pytest

from smart_llm.base import LLMResponse
from smart_llm.conversation import Conversation
from smart_llm.session import (
    NullConversationManager,
    SlidingWindowManager,
    SummarizingManager,
)


def _chat(n):
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_null_manager_is_passthrough():
    msgs = _chat(10)
    assert await NullConversationManager().apply(msgs) == msgs


@pytest.mark.asyncio
async def test_sliding_window_keeps_recent_messages():
    msgs = _chat(20)
    out = await SlidingWindowManager(max_messages=4).apply(msgs)
    assert len(out) == 4
    assert out[-1]["content"] == "m19"  # most-recent preserved


@pytest.mark.asyncio
async def test_sliding_window_below_bound_unchanged():
    msgs = _chat(3)
    assert await SlidingWindowManager(max_messages=8).apply(msgs) == msgs


@pytest.mark.asyncio
async def test_sliding_window_balances_orphan_tool_result():
    # A tool_result whose tool_use is trimmed away must be dropped.
    msgs = [
        {"role": "user", "content": "start"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
        },
        {"role": "assistant", "content": "done"},
    ]
    out = await SlidingWindowManager(max_messages=2).apply(msgs)
    # No dangling tool_result survives.
    for m in out:
        c = m.get("content")
        if isinstance(c, list):
            assert not any(b.get("type") == "tool_result" for b in c)


class _FakeSummarizer:
    async def analyze(self, prompt, **_):
        return LLMResponse(data={"content": "SUMMARY"}, provider="fake", metadata={})


@pytest.mark.asyncio
async def test_summarizing_below_trigger_unchanged():
    mgr = SummarizingManager(_FakeSummarizer(), keep_recent=2, trigger_turns=5)
    short = _chat(4)
    assert await mgr.apply(short) == short


@pytest.mark.asyncio
async def test_summarizing_above_trigger_compacts():
    mgr = SummarizingManager(_FakeSummarizer(), keep_recent=2, trigger_turns=5)
    out = await mgr.apply(_chat(10))
    assert len(out) == 3  # summary + 2 recent
    assert out[0]["content"].startswith("[Conversation summary")
    assert "SUMMARY" in out[0]["content"]
    assert out[-1]["content"] == "m9"


class _FakeAgent:
    def __init__(self):
        self.seen_lengths = []

    async def analyze(self, messages=None, **_):
        self.seen_lengths.append(len(messages or []))
        return LLMResponse(data={"content": "reply"}, provider="fake", metadata={})


@pytest.mark.asyncio
async def test_conversation_applies_manager():
    agent = _FakeAgent()
    conv = Conversation(agent, manager=SlidingWindowManager(max_messages=2))
    for t in ("a", "b", "c", "d"):
        await conv.send(t)
    # Window stays bounded: max_messages (2) + the appended assistant reply.
    assert len(conv.messages) <= 3
    # The provider never saw more than the bounded window either.
    assert max(agent.seen_lengths) <= 2


@pytest.mark.asyncio
async def test_conversation_without_manager_grows():
    agent = _FakeAgent()
    conv = Conversation(agent)  # no manager → unchanged behaviour
    await conv.send("a")
    await conv.send("b")
    assert len(conv.messages) == 4  # 2 user + 2 assistant
