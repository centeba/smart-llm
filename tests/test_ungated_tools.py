"""Deny-by-default for side-effecting tools when no policy gate is wired."""

import json

import pytest
from pydantic import BaseModel

from smart_llm.agent_loop import AgentTurn, ToolCall, run_agent_loop
from smart_llm.base import ActionTool


class _Args(BaseModel):
    x: int = 0


def _make_tool(risk_tier, recorder):
    class _T(ActionTool):
        args_model = _Args
        risk = risk_tier

        async def run_action(self, args, *, db_session):
            recorder.append(type(self).__name__)
            return {"ran": True}

    _T.__name__ = f"Tool_{risk_tier}"
    return _T


class _OneShotProvider:
    """Calls the tool once, then ends."""

    provider_type = "anthropic"
    model_name = "m"

    def __init__(self, tool_name):
        self.last_usage: dict = {}
        self._calls = 0
        self._tool_name = tool_name

    async def call_with_tools(self, system, messages, tools, **kw):
        self._calls += 1
        if self._calls == 1:
            return AgentTurn(
                content=None,
                tool_calls=[ToolCall(id="t1", name=self._tool_name, input={"x": 1})],
                stop_reason="tool_use",
                usage={},
            )
        return AgentTurn(
            content="done", tool_calls=[], stop_reason="end_turn", usage={}
        )

    def _build_assistant_tool_use_turn(self, turn):
        return {"role": "assistant", "content": []}

    def _build_tool_results_turn(self, results):
        # Surface the tool result content so the test can inspect the denial.
        self.last_results = results
        return {"role": "user", "content": []}


@pytest.fixture(autouse=True)
def _clear_escape_hatch(monkeypatch):
    # The suite-wide conftest sets the escape hatch; this module tests the
    # hardened default, so remove it (individual tests re-set it as needed).
    monkeypatch.delenv("SMART_LLM_ALLOW_UNGATED_TOOLS", raising=False)
    yield


@pytest.mark.asyncio
async def test_write_tool_denied_when_ungated():
    ran = []
    tool = _make_tool("write", ran)
    prov = _OneShotProvider("Tool_write")
    out = await run_agent_loop(prov, "sys", "hi", [tool()], db_session=None)
    assert out == "done"
    assert ran == []  # run_action never called
    # The synthetic denial was fed back to the model.
    denial = json.loads(prov.last_results[0]["content"])
    assert denial["status"] == "deny"
    assert "no policy gate" in denial["reason"]


@pytest.mark.asyncio
async def test_external_tool_denied_when_ungated():
    ran = []
    tool = _make_tool("external", ran)
    prov = _OneShotProvider("Tool_external")
    await run_agent_loop(prov, "sys", "hi", [tool()], db_session=None)
    assert ran == []


@pytest.mark.asyncio
async def test_read_tool_still_runs_when_ungated():
    ran = []
    tool = _make_tool("read", ran)
    prov = _OneShotProvider("Tool_read")
    await run_agent_loop(prov, "sys", "hi", [tool()], db_session=None)
    assert ran == ["Tool_read"]  # read-only tools remain dispatchable


@pytest.mark.asyncio
async def test_escape_hatch_restores_ungated_dispatch(monkeypatch):
    monkeypatch.setenv("SMART_LLM_ALLOW_UNGATED_TOOLS", "true")
    ran = []
    tool = _make_tool("write", ran)
    prov = _OneShotProvider("Tool_write")
    await run_agent_loop(prov, "sys", "hi", [tool()], db_session=None)
    assert ran == ["Tool_write"]  # legacy behaviour restored
