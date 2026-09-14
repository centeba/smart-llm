"""Tech-debt #5 / F2 streaming follow-up tests.

Covers the discriminated-union event contract between provider
``stream_with_tools`` and the ``run_agent_loop_stream`` driver. The
provider is mocked — these tests don't exercise real Anthropic SSE.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from smart_llm.agent_loop import (
    run_agent_loop_stream,
)
from smart_llm.base import ActionTool

# ── Test fixtures — minimal ActionTool + helpers ────────────────────────────


class _EchoArgs(BaseModel):
    msg: str


class _EchoTool(ActionTool):
    args_model = _EchoArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict:
        return {"echoed": args.msg}


async def _emit(events: list[dict]) -> AsyncIterator[dict]:
    """Build an async iterator that yields the given events."""
    for e in events:
        yield e


def _provider_with_stream(turns: list[list[dict]]):
    """Return a mock provider whose ``stream_with_tools`` yields each
    list of events in sequence (one per agent-loop turn)."""
    call_counter = {"n": 0}

    def _stream_with_tools(system_prompt, messages, action_tools):
        idx = call_counter["n"]
        call_counter["n"] += 1
        return _emit(turns[idx])

    prov = MagicMock()
    prov.stream_with_tools = _stream_with_tools
    prov.last_usage = {}
    # Build helpers used by the loop driver to append tool-result turns.
    prov._build_assistant_tool_use_turn = lambda turn: {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
            for tc in turn.tool_calls
        ],
    }
    prov._build_tool_results_turn = lambda results: {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": r["tool_call_id"],
                "content": r["content"],
            }
            for r in results
        ],
    }
    return prov, call_counter


# ── Single-turn end_turn path — pure text streaming ─────────────────────────


@pytest.mark.asyncio
async def test_stream_loop_text_only_end_turn():
    """No tool_use blocks → loop emits text deltas + turn_complete and
    returns after one provider call."""
    prov, counter = _provider_with_stream(
        [
            [
                {"type": "text_delta", "delta": "Hel"},
                {"type": "text_delta", "delta": "lo, "},
                {"type": "text_delta", "delta": "world!"},
                {
                    "type": "turn_complete",
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            ],
        ]
    )

    events = []
    async for ev in run_agent_loop_stream(prov, "sys", "hi", [], None):
        events.append(ev)

    text = "".join(e["delta"] for e in events if e["type"] == "text_delta")
    assert text == "Hello, world!"
    assert events[-1]["type"] == "turn_complete"
    assert counter["n"] == 1  # Single provider call — no second turn.
    # Usage accumulated onto provider.last_usage.
    assert prov.last_usage["input_tokens"] == 10
    assert prov.last_usage["output_tokens"] == 5


# ── Tool-use round → dispatch → second turn → end_turn ──────────────────────


@pytest.mark.asyncio
async def test_stream_loop_tool_use_then_end():
    """One tool_use block in turn 1 → driver dispatches → second
    provider call returns plain text → loop terminates."""
    prov, counter = _provider_with_stream(
        [
            # Turn 1 — model decides to call EchoTool.
            [
                {"type": "tool_use_start", "id": "tu_1", "name": "_EchoTool"},
                {
                    "type": "tool_use_input_delta",
                    "id": "tu_1",
                    "partial_json": '{"msg":',
                },
                {"type": "tool_use_input_delta", "id": "tu_1", "partial_json": '"hi"}'},
                {"type": "tool_use_stop", "id": "tu_1"},
                {
                    "type": "turn_complete",
                    "stop_reason": "tool_use",
                    "usage": {"input_tokens": 20, "output_tokens": 10},
                },
            ],
            # Turn 2 — model summarises the tool result and finishes.
            [
                {"type": "text_delta", "delta": "Done."},
                {
                    "type": "turn_complete",
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 15, "output_tokens": 3},
                },
            ],
        ]
    )

    tool = _EchoTool()
    events = []
    async for ev in run_agent_loop_stream(prov, "sys", "hi", [tool], None):
        events.append(ev)

    # Tool-use events surfaced to the consumer in order.
    tool_events = [e for e in events if e["type"].startswith("tool_use_")]
    assert [e["type"] for e in tool_events] == [
        "tool_use_start",
        "tool_use_input_delta",
        "tool_use_input_delta",
        "tool_use_stop",
    ]
    # Two turn_complete events — one per provider call.
    completes = [e for e in events if e["type"] == "turn_complete"]
    assert len(completes) == 2
    assert completes[-1]["stop_reason"] == "end_turn"

    # The driver made exactly two provider calls.
    assert counter["n"] == 2

    # Token usage is the SUM across both turns.
    assert prov.last_usage["input_tokens"] == 35  # 20 + 15
    assert prov.last_usage["output_tokens"] == 13  # 10 + 3


# ── Stream-level max_iterations enforcement ─────────────────────────────────


@pytest.mark.asyncio
async def test_stream_loop_max_iterations_emits_error():
    """A provider stuck in tool_use loops past ``max_iterations``
    surfaces an ``error`` event (not a raise) so the WS consumer can
    render a clean failure card."""
    # Two turns, both tool-use — exceeds max_iterations=2.
    loop_turn = [
        {"type": "tool_use_start", "id": "tu_x", "name": "_EchoTool"},
        {
            "type": "tool_use_input_delta",
            "id": "tu_x",
            "partial_json": '{"msg":"loop"}',
        },
        {"type": "tool_use_stop", "id": "tu_x"},
        {
            "type": "turn_complete",
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    ]
    prov, _ = _provider_with_stream([loop_turn, loop_turn])

    tool = _EchoTool()
    events = []
    async for ev in run_agent_loop_stream(
        prov, "sys", "hi", [tool], None, max_iterations=2
    ):
        events.append(ev)

    assert events[-1] == {
        "type": "error",
        "message": "Agent loop exceeded max_iterations=2",
    }


# ── S1: streamed tools honour the policy gate ───────────────────────────────


@pytest.mark.asyncio
async def test_stream_loop_policy_gate_blocks_unattended_write_tool():
    """A streamed write/external tool is NOT dispatched when the policy gate
    denies it (here: tool absent from the agent's allow-list → deny). Mirrors
    the safety harness the streaming router now wires in (finding S1)."""
    ran = {"called": False}

    class _DangerArgs(BaseModel):
        x: str = ""

    class _DangerTool(ActionTool):
        args_model = _DangerArgs
        read_only = False
        risk = "external"

        async def run_action(self, args: BaseModel, *, db_session: Any) -> dict:
            ran["called"] = True
            return {"did": "danger"}

    prov, _ = _provider_with_stream(
        [
            [
                {"type": "tool_use_start", "id": "tu_1", "name": "_DangerTool"},
                {"type": "tool_use_input_delta", "id": "tu_1", "partial_json": "{}"},
                {"type": "tool_use_stop", "id": "tu_1"},
                {"type": "turn_complete", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "delta": "ok"},
                {"type": "turn_complete", "stop_reason": "end_turn", "usage": {}},
            ],
        ]
    )

    from smart_llm.security.tool_policy import AgentRunContext, ToolPolicyGate

    gate = ToolPolicyGate(
        AgentRunContext(agent_id="a", acting_company_id="c", tool_modes={})
    )

    tool = _DangerTool()
    async for _ in run_agent_loop_stream(
        prov, "sys", "hi", [tool], None, policy_gate=gate
    ):
        pass

    assert ran["called"] is False  # gate blocked unattended dispatch


# ── Provider without stream_with_tools raises NotImplementedError ────────────


@pytest.mark.asyncio
async def test_stream_loop_raises_on_unsupported_provider():
    prov = MagicMock(spec=[])  # No stream_with_tools attribute.
    with pytest.raises(NotImplementedError, match="stream_with_tools"):
        async for _ in run_agent_loop_stream(prov, "sys", "hi", [], None):
            pass


# ── Malformed partial_json doesn't crash the loop ───────────────────────────


@pytest.mark.asyncio
async def test_stream_loop_tolerates_bad_tool_input_json():
    """If the model emits malformed JSON in input deltas, the tool
    runs with an empty dict and we don't blow up the whole stream."""
    prov, _ = _provider_with_stream(
        [
            [
                {"type": "tool_use_start", "id": "tu_b", "name": "_EchoTool"},
                {
                    "type": "tool_use_input_delta",
                    "id": "tu_b",
                    "partial_json": '{"msg": NOT_JSON',
                },  # malformed
                {"type": "tool_use_stop", "id": "tu_b"},
                {"type": "turn_complete", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "delta": "recovered"},
                {"type": "turn_complete", "stop_reason": "end_turn", "usage": {}},
            ],
        ]
    )

    # _EchoArgs requires "msg"; empty dict will fail validation in
    # tool dispatch but the loop logs + continues per existing
    # contract (see _dispatch_all error branch).
    tool = _EchoTool()
    events = []
    async for ev in run_agent_loop_stream(prov, "sys", "hi", [tool], None):
        events.append(ev)

    # Last event is the second turn's end-turn complete — we made
    # it to the second provider call despite the bad JSON.
    assert events[-1]["type"] == "turn_complete"
    assert events[-1]["stop_reason"] == "end_turn"
