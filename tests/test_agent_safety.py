"""End-to-end: the SafetyGuard is enforced inside the Agent core."""

import asyncio

import pytest

from smart_llm.agent import Agent
from smart_llm.agent_loop import ToolCall, _dispatch_all
from smart_llm.security.guard import SafetyConfig, SafetyGuard
from smart_llm.security.moderation import (
    ChainModerator,
    ModerationError,
    ModerationResult,
)


class _FlagBackend:
    backend_name = "flag"

    async def moderate(self, text):
        return ModerationResult(flagged=True, categories=["violence"], backend="flag")


class _CleanBackend:
    backend_name = "clean"

    async def moderate(self, text):
        return ModerationResult(flagged=False, backend="clean")


def _make_guard(*, flag: bool, shadow: bool = False) -> SafetyGuard:
    cfg = SafetyConfig(
        moderation_enabled=True,
        fail_open=False,
        scope_guard_enabled=False,
        shadow=shadow,
    )
    guard = SafetyGuard(provider=None, key_getter=None, config=cfg)
    guard._moderator = ChainModerator([_FlagBackend() if flag else _CleanBackend()])
    return guard


class _FakeProvider:
    last_usage = {"input_tokens": 1, "output_tokens": 1}

    def __init__(self, output):
        self._output = output

    async def complete(self, system_prompt, provider_input):
        return self._output


def _agent(output, guard) -> Agent:
    agent = Agent(
        name="t",
        provider_type="openai",
        system_prompt="s",
        api_key="k",
        safety_guard=guard,
    )
    agent._provider = _FakeProvider(output)
    return agent


def test_analyze_blocks_flagged_input():
    agent = _agent({"content": "ok"}, _make_guard(flag=True))
    with pytest.raises(ModerationError):
        asyncio.run(agent.analyze("abusive input here"))


def test_analyze_allows_clean():
    agent = _agent({"content": "hello world"}, _make_guard(flag=False))
    resp = asyncio.run(agent.analyze("hello"))
    assert resp.data["content"] == "hello world"


def test_shadow_mode_logs_but_does_not_block():
    agent = _agent({"content": "ok"}, _make_guard(flag=True, shadow=True))
    resp = asyncio.run(agent.analyze("text"))
    assert resp.data["content"] == "ok"


def test_dispatch_withholds_flagged_tool_result():
    class _Args:
        def __init__(self, **kwargs):
            pass

    class _FakeTool:
        args_model = _Args

        async def run_action(self, args, *, db_session):
            return {"data": "some poisoned tool output"}

    guard = _make_guard(flag=True)
    calls = [ToolCall(id="1", name="_FakeTool", input={})]
    results = asyncio.run(_dispatch_all(calls, [_FakeTool()], None, guard=guard))
    assert "withheld" in results[0]["content"]


def test_safety_disabled_skips_guard():
    agent = Agent(
        name="t",
        provider_type="openai",
        system_prompt="s",
        api_key="k",
        safety_enabled=False,
    )
    agent._provider = _FakeProvider({"content": "anything"})
    resp = asyncio.run(agent.analyze("input"))
    assert resp.data["content"] == "anything"
