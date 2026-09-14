"""Tests for the autonomous-agent tool-policy gate (P3 + P5 logic)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from smart_llm.agent_loop import ToolCall, _dispatch_all
from smart_llm.base import ActionTool
from smart_llm.security.tool_policy import (
    AgentRunContext,
    ToolPolicyGate,
    resolve_tool_policy,
)

# ── resolve_tool_policy matrix ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode,risk,expected",
    [
        (None, "read", "deny"),  # not allow-listed → deny
        (None, "external", "deny"),
        ("deny", "read", "deny"),
        ("require_approval", "read", "approval_required"),
        ("allow", "external", "allow"),  # admin force opt-in
        ("auto", "read", "allow"),  # risk-default: read runs
        ("auto", "write", "approval_required"),
        ("auto", "external", "approval_required"),
    ],
)
def test_resolve_tool_policy_matrix(mode, risk, expected):
    assert resolve_tool_policy(mode, risk) == expected


# ── Gate evaluation ───────────────────────────────────────────────────────────


class _Args(BaseModel):
    x: int = 1
    target_company_id: str | None = None


class _ReadTool(ActionTool):
    args_model = _Args
    read_only = True

    async def run_action(self, args, *, db_session):
        return {"ok": True}


class _SendTool(ActionTool):
    args_model = _Args
    risk = "external"
    cross_tenant_arg = "target_company_id"

    async def run_action(self, args, *, db_session):
        return {"sent": True}


def _ctx(modes, **kw):
    return AgentRunContext(
        agent_id="agent-1", acting_company_id="A", tool_modes=modes, **kw
    )


@pytest.mark.asyncio
async def test_gate_allows_read_auto():
    gate = ToolPolicyGate(_ctx({"read_tool": "auto"}))
    d = await gate.evaluate(
        tool_name="read_tool", tool_cls=_ReadTool, validated_args=_Args()
    )
    assert d.decision == "allow"


@pytest.mark.asyncio
async def test_gate_requires_approval_for_external_auto():
    gate = ToolPolicyGate(_ctx({"send_tool": "auto"}))
    d = await gate.evaluate(
        tool_name="send_tool", tool_cls=_SendTool, validated_args=_Args()
    )
    assert d.decision == "approval_required"


@pytest.mark.asyncio
async def test_gate_denies_unlisted_tool():
    gate = ToolPolicyGate(_ctx({}))  # send_tool not in allow-list
    d = await gate.evaluate(
        tool_name="send_tool", tool_cls=_SendTool, validated_args=_Args()
    )
    assert d.decision == "deny"


# ── Cross-company deny-by-default (P5) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_company_denied_without_checker():
    # External tool, force-allow mode, but targets company B with no authz wiring.
    gate = ToolPolicyGate(_ctx({"send_tool": "allow"}))
    d = await gate.evaluate(
        tool_name="send_tool",
        tool_cls=_SendTool,
        validated_args=_Args(target_company_id="B"),
    )
    assert d.decision == "deny"
    assert d.target_company_id == "B"


@pytest.mark.asyncio
async def test_cross_company_allowed_with_grant():
    async def checker(agent_id, target, action):
        return target == "B" and action == "send_tool"

    gate = ToolPolicyGate(_ctx({"send_tool": "allow"}, authz_checker=checker))
    d = await gate.evaluate(
        tool_name="send_tool",
        tool_cls=_SendTool,
        validated_args=_Args(target_company_id="B"),
    )
    assert d.decision == "allow"


@pytest.mark.asyncio
async def test_cross_company_denied_when_checker_false():
    async def checker(agent_id, target, action):
        return False

    gate = ToolPolicyGate(_ctx({"send_tool": "allow"}, authz_checker=checker))
    d = await gate.evaluate(
        tool_name="send_tool",
        tool_cls=_SendTool,
        validated_args=_Args(target_company_id="B"),
    )
    assert d.decision == "deny"


# ── _dispatch_all integration: deny never runs the tool ───────────────────────


@pytest.mark.asyncio
async def test_dispatch_deny_does_not_run_action():
    ran = {"called": False}

    class _Spy(ActionTool):
        args_model = _Args
        risk = "external"

        async def run_action(self, args, *, db_session):
            ran["called"] = True
            return {"sent": True}

    spy = _Spy()
    spy._registry_name = "spy_tool"  # type: ignore[attr-defined]
    gate = ToolPolicyGate(_ctx({"spy_tool": "deny"}))
    results = await _dispatch_all(
        [ToolCall(id="c1", name="spy_tool", input={})],
        [spy],
        db_session=None,
        policy_gate=gate,
    )
    assert ran["called"] is False
    assert results[0]["name"] == "spy_tool"
    assert "deny" in results[0]["content"]


@pytest.mark.asyncio
async def test_dispatch_allow_runs_action():
    spy = _ReadTool()
    spy._registry_name = "read_tool"  # type: ignore[attr-defined]
    gate = ToolPolicyGate(_ctx({"read_tool": "auto"}))
    results = await _dispatch_all(
        [ToolCall(id="c1", name="read_tool", input={})],
        [spy],
        db_session=None,
        policy_gate=gate,
    )
    assert '"ok": true' in results[0]["content"]


# ── run_one_turn (durable path) ───────────────────────────────────────────────


class _FakeProvider:
    """Minimal provider exposing call_with_tools, returning a scripted turn."""

    def __init__(self, turn):
        self._turn = turn

    async def call_with_tools(self, system_prompt, messages, action_tools):
        return self._turn


@pytest.mark.asyncio
async def test_run_one_turn_final():
    from smart_llm.agent_loop import AgentTurn, run_one_turn

    prov = _FakeProvider(
        AgentTurn(content="done", tool_calls=[], stop_reason="end_turn")
    )
    out = await run_one_turn(prov, "sys", [{"role": "user", "content": "hi"}], [])
    assert out["status"] == "final" and out["content"] == "done"


@pytest.mark.asyncio
async def test_run_one_turn_tool_calls_with_decision():
    from smart_llm.agent_loop import AgentTurn, run_one_turn
    from smart_llm.agent_loop import ToolCall as TC

    send = _SendTool()
    send._registry_name = "send_tool"  # type: ignore[attr-defined]
    turn = AgentTurn(
        content=None,
        tool_calls=[TC(id="c1", name="send_tool", input={})],
        stop_reason="tool_use",
    )
    gate = ToolPolicyGate(_ctx({"send_tool": "auto"}))  # external+auto → approval
    out = await run_one_turn(
        _FakeProvider(turn),
        "sys",
        [{"role": "user", "content": "hi"}],
        [send],
        policy_gate=gate,
    )
    assert out["status"] == "tool_calls"
    assert out["tool_calls"][0]["decision"] == "approval_required"
