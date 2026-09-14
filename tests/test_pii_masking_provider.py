"""MaskingProvider — the egress choke point.

Asserts the two guarantees end to end: only tokens reach the inner provider,
and the model's output is re-hydrated for the caller. Also covers fail-closed
behaviour, vision gating, and transparent attribute delegation.
"""

import json

import pytest

from smart_llm.agent_loop import AgentTurn, ToolCall
from smart_llm.pii.firewall import PiiFirewall, PiiMaskingError
from smart_llm.pii.masking_provider import MaskingProvider

SSN = "123-45-6789"
EMAIL = "jane@example.com"


class FakeProvider:
    """Records what it was sent and echoes it back (so restoration round-trips)."""

    NAME = "fake"

    def __init__(self):
        self.model_name = "fake-1"
        self.last_usage = {"input_tokens": 3, "output_tokens": 5}
        self.seen_system = None
        self.seen_input = None
        self.seen_image = None
        self.complete_calls = 0
        # Scripted outputs for the streaming-with-tools test.
        self.script_events: list[dict] = []

    async def complete(self, system, user_prompt):
        self.complete_calls += 1
        self.seen_system = system
        self.seen_input = user_prompt
        # ensure_ascii=False so echoed placeholder glyphs stay literal, the way
        # a model emits them in its output (not as \uXXXX escapes).
        text = user_prompt if isinstance(user_prompt, str) else json.dumps(user_prompt, ensure_ascii=False)
        return {"content": text}

    async def stream(self, system, user_prompt):
        self.seen_system = system
        self.seen_input = user_prompt
        text = user_prompt if isinstance(user_prompt, str) else json.dumps(user_prompt, ensure_ascii=False)
        for ch in text:
            yield ch

    async def complete_with_image(self, system, prompt, image_bytes, mime_type="image/jpeg"):
        self.seen_image = (system, prompt, image_bytes, mime_type)
        return [{"echo": prompt}]

    async def call_with_tools(self, system, messages, action_tools, **kwargs):
        self.seen_system = system
        self.seen_input = messages
        echo = json.dumps(messages, ensure_ascii=False)
        return AgentTurn(
            content=echo,
            tool_calls=[ToolCall(id="c1", name="lookup", input={"echo": echo})],
            stop_reason="tool_use",
            usage={},
        )

    async def stream_with_tools(self, system, messages, action_tools, **kwargs):
        self.seen_system = system
        self.seen_input = messages
        for ev in self.script_events:
            yield ev

    def _build_assistant_tool_use_turn(self, turn):
        return {"role": "assistant", "content": turn.content}


def _mp(policy="enforce", **kw):
    inner = FakeProvider()
    return MaskingProvider(inner, PiiFirewall(), policy, **kw), inner


# ── complete ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_masks_egress_and_rehydrates_output():
    mp, inner = _mp()
    out = await mp.complete(f"agent for {EMAIL}", f"look up {SSN}")
    # Inner saw ONLY tokens — no raw PII crossed the boundary.
    assert SSN not in inner.seen_input
    assert EMAIL not in inner.seen_system
    assert "⟦SSN_1⟧" in inner.seen_input
    # Caller got the real value back (round-tripped).
    assert SSN in out["content"]


@pytest.mark.asyncio
async def test_complete_multi_turn_messages_masked():
    mp, inner = _mp()
    messages = [{"role": "user", "content": f"my card is 4111 1111 1111 1111 and ssn {SSN}"}]
    await mp.complete("sys", messages)
    blob = json.dumps(inner.seen_input)
    assert SSN not in blob
    assert "4111 1111 1111 1111" not in blob


# ── stream ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_masks_egress_and_rehydrates():
    mp, inner = _mp()
    chunks = [c async for c in mp.stream("sys", f"contact {SSN}")]
    joined = "".join(chunks)
    assert SSN not in json.dumps(inner.seen_input)  # inner never saw raw SSN
    assert SSN in joined  # caller's stream re-hydrated


# ── fail-closed ────────────────────────────────────────────────────────────────


class _BoomFirewall(PiiFirewall):
    def mask_payload(self, system, provider_input, vault):
        raise RuntimeError("detector exploded")


@pytest.mark.asyncio
async def test_enforce_fails_closed_before_egress():
    inner = FakeProvider()
    mp = MaskingProvider(inner, _BoomFirewall(), "enforce")
    with pytest.raises(PiiMaskingError):
        await mp.complete("sys", f"ssn {SSN}")
    # The inner provider was NEVER called — raw content did not egress.
    assert inner.complete_calls == 0
    assert mp.masking_summary()["fail_closed"] is True


@pytest.mark.asyncio
async def test_detect_only_proceeds_on_masking_error():
    inner = FakeProvider()
    mp = MaskingProvider(inner, _BoomFirewall(), "detect-only")
    out = await mp.complete("sys", "hello")
    assert inner.complete_calls == 1  # never blocks under detect-only
    assert out["content"] == "hello"


# ── vision gating ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vision_blocked_under_enforce():
    mp, inner = _mp("enforce")
    with pytest.raises(PiiMaskingError):
        await mp.complete_with_image("sys", "describe", b"\x89PNG", "image/png")
    assert inner.seen_image is None
    assert mp.masking_summary()["vision_blocked"] == 1


@pytest.mark.asyncio
async def test_vision_allowed_with_escape_hatch_and_masks_prompt():
    mp, inner = _mp("enforce", allow_vision_pii=True)
    await mp.complete_with_image("sys", f"caption for {SSN}", b"img", "image/png")
    # Call went through and the text prompt was masked.
    assert inner.seen_image is not None
    assert SSN not in inner.seen_image[1]


@pytest.mark.asyncio
async def test_vision_allowed_under_detect_only_audits_flag():
    mp, inner = _mp("detect-only")
    await mp.complete_with_image("sys", "caption", b"img", "image/png")
    assert inner.seen_image is not None
    assert mp.masking_summary()["vision_unmasked"] == 1


# ── call_with_tools ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_with_tools_masks_and_restores_turn():
    mp, inner = _mp()
    messages = [{"role": "user", "content": f"find {SSN}"}]
    turn = await mp.call_with_tools("sys", messages, [])
    assert SSN not in json.dumps(inner.seen_input)  # egress masked
    assert SSN in turn.content  # content re-hydrated
    assert SSN in turn.tool_calls[0].input["echo"]  # tool-arg re-hydrated


# ── stream_with_tools ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_with_tools_restores_text_and_tool_args():
    mp, inner = _mp()
    # Pre-mint tokens on the provider's vault, then script the inner stream to
    # emit them (split across fragments) — mirrors a provider echoing masked PII.
    ssn_tok = mp._vault.tokenize(SSN, "SSN")
    email_tok = mp._vault.tokenize(EMAIL, "EMAIL")
    arg_json = json.dumps({"q": email_tok}, ensure_ascii=False)
    mid = len(arg_json) // 2
    inner.script_events = [
        {"type": "text_delta", "delta": f"result {ssn_tok[:3]}"},
        {"type": "text_delta", "delta": f"{ssn_tok[3:]} end"},
        {"type": "tool_use_start", "id": "c1", "name": "lookup"},
        {"type": "tool_use_input_delta", "id": "c1", "partial_json": arg_json[:mid]},
        {"type": "tool_use_input_delta", "id": "c1", "partial_json": arg_json[mid:]},
        {"type": "tool_use_stop", "id": "c1"},
        {"type": "turn_complete", "stop_reason": "tool_use", "usage": {}},
    ]

    text_out = []
    arg_out = []
    for ev in [e async for e in mp.stream_with_tools("sys", [{"role": "user", "content": "hi"}], [])]:
        if ev["type"] == "text_delta":
            text_out.append(ev["delta"])
        elif ev["type"] == "tool_use_input_delta":
            arg_out.append(ev["partial_json"])

    assert "".join(text_out) == f"result {SSN} end"
    assembled = json.loads("".join(arg_out))
    assert assembled["q"] == EMAIL


# ── attribute delegation ───────────────────────────────────────────────────────


def test_getattr_delegates_to_inner():
    mp, inner = _mp()
    assert mp.last_usage == inner.last_usage
    assert mp.model_name == "fake-1"
    assert mp.NAME == "fake"
    # The loop calls this helper on the provider via duck-typing.
    assert callable(mp._build_assistant_tool_use_turn)
