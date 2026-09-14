"""Per-provider ``stream_with_tools`` event-emission tests.

Mocks each SDK's chunk shape and asserts the provider yields the
discriminated-union events documented in :mod:`smart_llm.agent_loop`.
Driver-side semantics are covered separately in
``test_streaming_tools.py``.
"""

from __future__ import annotations

import json
import types as _stdlib_types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from smart_llm.base import ActionTool

# ── Shared ActionTool fixture ───────────────────────────────────────────────


class _EchoArgs(BaseModel):
    msg: str


class _EchoTool(ActionTool):
    args_model = _EchoArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict:
        return {"echoed": args.msg}


# ── Helpers to build "duck-typed" SDK chunks via SimpleNamespace ────────────


def _ns(**kw):
    return _stdlib_types.SimpleNamespace(**kw)


# ── OpenAI ──────────────────────────────────────────────────────────────────


async def _async_iter(items):
    for it in items:
        yield it


@pytest.mark.asyncio
async def test_openai_stream_with_tools_text_only():
    """Plain text deltas + ``finish_reason=stop`` → ``end_turn``."""
    chunks = [
        _ns(
            choices=[
                _ns(delta=_ns(content="Hel", tool_calls=None), finish_reason=None)
            ],
            usage=None,
        ),
        _ns(
            choices=[
                _ns(delta=_ns(content="lo!", tool_calls=None), finish_reason="stop")
            ],
            usage=None,
        ),
        # Final usage-only frame (stream_options.include_usage=True).
        _ns(choices=[], usage=_ns(prompt_tokens=10, completion_tokens=5)),
    ]

    with patch("smart_llm.providers.openai.AsyncOpenAI") as MockSDK:
        client = MockSDK.return_value
        client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        from smart_llm.providers.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="k", model_name="gpt-4o")
        events = []
        async for ev in provider.stream_with_tools(
            "sys", [{"role": "user", "content": "hi"}], []
        ):
            events.append(ev)

    text = "".join(e["delta"] for e in events if e["type"] == "text_delta")
    assert text == "Hello!"
    last = events[-1]
    assert last["type"] == "turn_complete"
    assert last["stop_reason"] == "end_turn"
    assert last["usage"] == {"input_tokens": 10, "output_tokens": 5}


@pytest.mark.asyncio
async def test_openai_stream_with_tools_tool_call_chunks():
    """``tool_calls`` arrive in pieces — name on the first chunk,
    ``arguments`` JSON streamed in fragments; finish_reason=
    ``tool_calls`` maps to ``stop_reason=tool_use``."""
    chunks = [
        # First tool-call chunk: id + name only.
        _ns(
            choices=[
                _ns(
                    delta=_ns(
                        content=None,
                        tool_calls=[
                            _ns(
                                index=0,
                                id="call_abc",
                                function=_ns(name="_EchoTool", arguments=""),
                            )
                        ],
                    ),
                    finish_reason=None,
                )
            ],
            usage=None,
        ),
        # arguments delta #1.
        _ns(
            choices=[
                _ns(
                    delta=_ns(
                        content=None,
                        tool_calls=[
                            _ns(
                                index=0,
                                id=None,
                                function=_ns(name=None, arguments='{"msg":'),
                            )
                        ],
                    ),
                    finish_reason=None,
                )
            ],
            usage=None,
        ),
        # arguments delta #2.
        _ns(
            choices=[
                _ns(
                    delta=_ns(
                        content=None,
                        tool_calls=[
                            _ns(
                                index=0,
                                id=None,
                                function=_ns(name=None, arguments='"hi"}'),
                            )
                        ],
                    ),
                    finish_reason=None,
                )
            ],
            usage=None,
        ),
        # finish.
        _ns(
            choices=[
                _ns(
                    delta=_ns(content=None, tool_calls=None), finish_reason="tool_calls"
                )
            ],
            usage=None,
        ),
        _ns(choices=[], usage=_ns(prompt_tokens=12, completion_tokens=8)),
    ]

    with patch("smart_llm.providers.openai.AsyncOpenAI") as MockSDK:
        client = MockSDK.return_value
        client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        from smart_llm.providers.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="k", model_name="gpt-4o")
        events = []
        async for ev in provider.stream_with_tools(
            "sys", [{"role": "user", "content": "hi"}], [_EchoTool()]
        ):
            events.append(ev)

    types_seen = [e["type"] for e in events]
    # Expect: one start, two input_delta, one stop, then turn_complete.
    assert types_seen.count("tool_use_start") == 1
    assert types_seen.count("tool_use_input_delta") == 2
    assert types_seen.count("tool_use_stop") == 1
    assert events[-1]["type"] == "turn_complete"
    assert events[-1]["stop_reason"] == "tool_use"

    # Start event has the right id + name.
    start = next(e for e in events if e["type"] == "tool_use_start")
    assert start["id"] == "call_abc"
    assert start["name"] == "_EchoTool"

    # Concatenated input deltas parse into the expected args.
    deltas = [e["partial_json"] for e in events if e["type"] == "tool_use_input_delta"]
    assert json.loads("".join(deltas)) == {"msg": "hi"}


@pytest.mark.asyncio
async def test_openai_stream_with_tools_synthesises_id_when_missing():
    """First tool-call chunk has no id → we synthesise one
    (``call_<index>``) so later deltas still route correctly."""
    chunks = [
        _ns(
            choices=[
                _ns(
                    delta=_ns(
                        content=None,
                        tool_calls=[
                            _ns(
                                index=0,
                                id=None,
                                function=_ns(name="_EchoTool", arguments='{"msg":"x"}'),
                            )
                        ],
                    ),
                    finish_reason=None,
                )
            ],
            usage=None,
        ),
        _ns(
            choices=[
                _ns(
                    delta=_ns(content=None, tool_calls=None), finish_reason="tool_calls"
                )
            ],
            usage=None,
        ),
    ]
    with patch("smart_llm.providers.openai.AsyncOpenAI") as MockSDK:
        client = MockSDK.return_value
        client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

        from smart_llm.providers.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="k", model_name="gpt-4o")
        events = [
            e
            async for e in provider.stream_with_tools(
                "sys", [{"role": "user", "content": "hi"}], [_EchoTool()]
            )
        ]
    start = next(e for e in events if e["type"] == "tool_use_start")
    assert start["id"] == "call_0"  # synthesised


@pytest.mark.asyncio
async def test_openai_stream_with_tools_error_event_on_exception():
    """Provider raising during streaming surfaces as an ``error``
    event rather than propagating — keeps the agent-loop driver's
    consumer in control of recovery."""
    with patch("smart_llm.providers.openai.AsyncOpenAI") as MockSDK:
        client = MockSDK.return_value
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))

        from smart_llm.providers.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="k", model_name="gpt-4o")
        events = [
            e
            async for e in provider.stream_with_tools(
                "sys", [{"role": "user", "content": "hi"}], []
            )
        ]
    assert events[-1]["type"] == "error"
    assert "boom" in events[-1]["message"]


# ── Gemini ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gemini_stream_with_tools_text_only(monkeypatch):
    """Text-only stream → text_delta events + end_turn."""
    chunks = [
        _ns(
            candidates=[_ns(content=_ns(parts=[_ns(text="Hi ", function_call=None)]))],
            usage_metadata=None,
        ),
        _ns(
            candidates=[
                _ns(content=_ns(parts=[_ns(text="there", function_call=None)]))
            ],
            usage_metadata=_ns(prompt_token_count=5, candidates_token_count=2),
        ),
    ]
    with patch("smart_llm.providers.gemini.genai") as MockGenai:
        client = MockGenai.Client.return_value
        client.models.generate_content_stream = MagicMock(return_value=iter(chunks))

        from smart_llm.providers.gemini import GeminiProvider

        provider = GeminiProvider(api_key="k", model_name="gemini-2.5-flash")
        events = [
            e
            async for e in provider.stream_with_tools(
                "sys", [{"role": "user", "content": "hi"}], []
            )
        ]

    text = "".join(e["delta"] for e in events if e["type"] == "text_delta")
    assert text == "Hi there"
    assert events[-1]["type"] == "turn_complete"
    assert events[-1]["stop_reason"] == "end_turn"
    assert events[-1]["usage"]["input_tokens"] == 5
    assert events[-1]["usage"]["output_tokens"] == 2


@pytest.mark.asyncio
async def test_gemini_stream_with_tools_function_call_emits_full_sequence():
    """``function_call`` part → tool_use_start + tool_use_input_delta
    (full args JSON in one shot) + tool_use_stop."""
    fc = _ns(name="_EchoTool", args={"msg": "hi"}, id=None)
    chunks = [
        _ns(
            candidates=[_ns(content=_ns(parts=[_ns(text=None, function_call=fc)]))],
            usage_metadata=_ns(prompt_token_count=8, candidates_token_count=4),
        ),
    ]
    with patch("smart_llm.providers.gemini.genai") as MockGenai:
        client = MockGenai.Client.return_value
        client.models.generate_content_stream = MagicMock(return_value=iter(chunks))

        from smart_llm.providers.gemini import GeminiProvider

        provider = GeminiProvider(api_key="k", model_name="gemini-2.5-flash")
        events = [
            e
            async for e in provider.stream_with_tools(
                "sys", [{"role": "user", "content": "hi"}], [_EchoTool()]
            )
        ]

    types_seen = [e["type"] for e in events]
    assert types_seen[0] == "tool_use_start"
    assert types_seen[1] == "tool_use_input_delta"
    assert types_seen[2] == "tool_use_stop"
    assert events[-1]["type"] == "turn_complete"
    assert events[-1]["stop_reason"] == "tool_use"

    # The single input_delta carries the whole args dict JSON-encoded.
    delta = next(e for e in events if e["type"] == "tool_use_input_delta")
    assert json.loads(delta["partial_json"]) == {"msg": "hi"}


@pytest.mark.asyncio
async def test_gemini_stream_with_tools_error_event_on_exception():
    """SDK raising during stream start surfaces as ``error``."""
    with patch("smart_llm.providers.gemini.genai") as MockGenai:
        client = MockGenai.Client.return_value
        client.models.generate_content_stream = MagicMock(
            side_effect=RuntimeError("kaboom")
        )

        from smart_llm.providers.gemini import GeminiProvider

        provider = GeminiProvider(api_key="k", model_name="gemini-2.5-flash")
        events = [
            e
            async for e in provider.stream_with_tools(
                "sys", [{"role": "user", "content": "hi"}], []
            )
        ]
    assert events[-1]["type"] == "error"
    assert "kaboom" in events[-1]["message"]
