"""Tests for smart_llm.agent_loop — the F2 multi-turn agent loop driver.

All tests are unit-level: no live LLM calls.  The provider is mocked via
an object that exposes ``call_with_tools`` as an async callable, plus
optional ``_build_assistant_tool_use_turn`` / ``_build_tool_results_turn``
helpers.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from smart_llm.agent_loop import (
    AgentTurn,
    ToolCall,
    _build_assistant_turn,
    _build_tool_results_turn,
    _dispatch_all,
    run_agent_loop,
)
from smart_llm.base import ActionTool

# ── Helpers ────────────────────────────────────────────────────────────────────


class _Adder(ActionTool):
    """Simple test tool: adds two integers."""

    class Args(BaseModel):
        a: int
        b: int

    args_model = Args

    async def run_action(self, args, *, db_session=None) -> dict[str, Any]:
        return {"sum": args.a + args.b}


def _make_provider(turns: list[AgentTurn]):
    """Return a mock provider that yields turns in order."""
    provider = MagicMock()
    provider.call_with_tools = AsyncMock(side_effect=turns)
    provider.last_usage = {}
    return provider


# ── ToolCall / AgentTurn dataclasses ──────────────────────────────────────────


def test_tool_call_fields():
    tc = ToolCall(id="123", name="foo", input={"x": 1})
    assert tc.id == "123"
    assert tc.name == "foo"
    assert tc.input == {"x": 1}


def test_agent_turn_defaults():
    turn = AgentTurn(content=None, tool_calls=[], stop_reason="end_turn")
    assert turn.usage == {}


# ── _dispatch_all ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_known_tool():
    adder = _Adder()
    results = await _dispatch_all(
        [ToolCall(id="c1", name="_Adder", input={"a": 3, "b": 4})],
        [adder],
        db_session=None,
    )
    assert len(results) == 1
    content = json.loads(results[0]["content"])
    assert content["sum"] == 7


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error():
    results = await _dispatch_all(
        [ToolCall(id="c2", name="ghost_tool", input={})],
        [_Adder()],
        db_session=None,
    )
    assert "Unknown tool" in results[0]["content"]


@pytest.mark.asyncio
async def test_dispatch_validation_error_returns_json_error():
    results = await _dispatch_all(
        [ToolCall(id="c3", name="_Adder", input={"a": "not-a-number", "b": 1})],
        [_Adder()],
        db_session=None,
    )
    payload = json.loads(results[0]["content"])
    assert "error" in payload


# ── _build_assistant_turn ─────────────────────────────────────────────────────


def test_build_assistant_turn_uses_provider_method():
    provider = MagicMock()
    provider._build_assistant_tool_use_turn = MagicMock(
        return_value={"role": "assistant"}
    )
    turn = AgentTurn(content="hi", tool_calls=[], stop_reason="end_turn")
    result = _build_assistant_turn(turn, provider)
    assert result == {"role": "assistant"}
    provider._build_assistant_tool_use_turn.assert_called_once_with(turn)


def test_build_assistant_turn_falls_back_to_anthropic_format():
    """Provider without _build_assistant_tool_use_turn → Anthropic default."""
    provider = MagicMock(spec=[])  # no helper method
    tc = ToolCall(id="tid", name="my_tool", input={"x": 1})
    turn = AgentTurn(content=None, tool_calls=[tc], stop_reason="tool_use")
    result = _build_assistant_turn(turn, provider)
    assert result["role"] == "assistant"
    assert result["content"][0]["type"] == "tool_use"
    assert result["content"][0]["id"] == "tid"


# ── _build_tool_results_turn ──────────────────────────────────────────────────


def test_build_tool_results_turn_uses_provider_method():
    provider = MagicMock()
    provider._build_tool_results_turn = MagicMock(return_value={"role": "user"})
    results = [{"tool_call_id": "x", "name": "y", "content": "{}"}]
    out = _build_tool_results_turn(results, provider)
    assert out == {"role": "user"}


def test_build_tool_results_turn_falls_back_to_anthropic_format():
    provider = MagicMock(spec=[])
    results = [{"tool_call_id": "t1", "name": "y", "content": "{}"}]
    out = _build_tool_results_turn(results, provider)
    assert out["role"] == "user"
    assert out["content"][0]["type"] == "tool_result"
    assert out["content"][0]["tool_use_id"] == "t1"


# ── run_agent_loop ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_terminates_on_end_turn_immediately():
    provider = _make_provider(
        [
            AgentTurn(content="Hello!", tool_calls=[], stop_reason="end_turn"),
        ]
    )
    result = await run_agent_loop(provider, "sys", "hi", [], db_session=None)
    assert result == "Hello!"
    assert provider.call_with_tools.call_count == 1


@pytest.mark.asyncio
async def test_loop_terminates_when_no_tool_calls():
    """stop_reason != 'end_turn' but no tool calls → still terminates."""
    provider = _make_provider(
        [
            AgentTurn(content="Done.", tool_calls=[], stop_reason="stop"),
        ]
    )
    result = await run_agent_loop(provider, "sys", "hi", [], db_session=None)
    assert result == "Done."


@pytest.mark.asyncio
async def test_loop_dispatches_one_tool_then_finishes():
    adder = _Adder()
    tc = ToolCall(id="id1", name="_Adder", input={"a": 10, "b": 5})
    provider = _make_provider(
        [
            AgentTurn(content=None, tool_calls=[tc], stop_reason="tool_use"),
            AgentTurn(content="The sum is 15.", tool_calls=[], stop_reason="end_turn"),
        ]
    )
    result = await run_agent_loop(provider, "sys", "add 10+5", [adder], db_session=None)
    assert result == "The sum is 15."
    assert provider.call_with_tools.call_count == 2


@pytest.mark.asyncio
async def test_loop_accumulates_token_usage():
    provider = _make_provider(
        [
            AgentTurn(
                content=None,
                tool_calls=[ToolCall(id="x", name="_Adder", input={"a": 1, "b": 2})],
                stop_reason="tool_use",
                usage={"input_tokens": 10, "output_tokens": 5},
            ),
            AgentTurn(
                content="done",
                tool_calls=[],
                stop_reason="end_turn",
                usage={"input_tokens": 8, "output_tokens": 3},
            ),
        ]
    )
    provider.last_usage = {}
    await run_agent_loop(provider, "sys", "hi", [_Adder()], db_session=None)
    assert provider.last_usage["input_tokens"] == 18
    assert provider.last_usage["output_tokens"] == 8


@pytest.mark.asyncio
async def test_loop_raises_on_max_iterations():
    """Infinite tool-call loop → RuntimeError after max_iterations."""
    tc = ToolCall(id="i", name="_Adder", input={"a": 1, "b": 1})
    infinite_turn = AgentTurn(content=None, tool_calls=[tc], stop_reason="tool_use")
    provider = _make_provider([infinite_turn] * 20)
    with pytest.raises(RuntimeError, match="max_iterations"):
        await run_agent_loop(
            provider, "sys", "hi", [_Adder()], db_session=None, max_iterations=3
        )
    assert provider.call_with_tools.call_count == 3


@pytest.mark.asyncio
async def test_loop_handles_openai_list_tool_results():
    """OpenAI returns a list from _build_tool_results_turn; loop must extend."""
    adder = _Adder()
    tc = ToolCall(id="id1", name="_Adder", input={"a": 2, "b": 3})

    provider = _make_provider(
        [
            AgentTurn(content=None, tool_calls=[tc], stop_reason="tool_use"),
            AgentTurn(content="5", tool_calls=[], stop_reason="end_turn"),
        ]
    )
    # Override the tool results builder to return a list (OpenAI shape)
    provider._build_tool_results_turn = MagicMock(
        return_value=[{"role": "tool", "tool_call_id": "id1", "content": '{"sum":5}'}]
    )
    provider._build_assistant_tool_use_turn = MagicMock(
        return_value={"role": "assistant", "content": None, "tool_calls": []}
    )

    result = await run_agent_loop(provider, "sys", "hi", [adder], db_session=None)
    assert result == "5"
    # The loop must have extended messages with the list
    second_call_messages = provider.call_with_tools.call_args_list[1][0][1]
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
