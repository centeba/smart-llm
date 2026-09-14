"""Agent-to-agent hop authorization in the orchestrator (deny-by-default)."""

import pytest

from smart_llm.orchestrator import AgentGraphSpec, HopContext, run_agent_graph


def _spec():
    return AgentGraphSpec.from_dict(
        {
            "entry": "root",
            "nodes": [
                {"id": "root", "agent_id": "ag-root", "next": ["a", "b"]},
                {"id": "a", "agent_id": "ag-a"},
                {"id": "b", "agent_id": "ag-b"},
            ],
        }
    )


def _runner(calls):
    async def runner(agent_id, input_text):
        calls.append(agent_id)
        return {"ok": True, "from": agent_id}

    return runner


@pytest.mark.asyncio
async def test_no_authorizer_runs_all_hops():
    calls: list[str] = []
    await run_agent_graph(_spec(), "hi", runner=_runner(calls))
    assert set(calls) == {"ag-root", "ag-a", "ag-b"}


@pytest.mark.asyncio
async def test_authorizer_allows_all():
    calls: list[str] = []

    async def allow(ctx: HopContext) -> bool:
        return True

    await run_agent_graph(_spec(), "hi", runner=_runner(calls), hop_authorizer=allow)
    assert set(calls) == {"ag-root", "ag-a", "ag-b"}


@pytest.mark.asyncio
async def test_denied_hop_not_invoked_and_recorded():
    calls: list[str] = []

    async def deny_b(ctx: HopContext) -> bool:
        return ctx.to_node_id != "b"

    res = await run_agent_graph(
        _spec(), "hi", runner=_runner(calls), hop_authorizer=deny_b
    )
    assert "ag-b" not in calls  # denied agent never ran
    assert "ag-a" in calls and "ag-root" in calls
    assert res["results"]["b"]["denied"] is True


@pytest.mark.asyncio
async def test_authorizer_raise_fails_closed():
    calls: list[str] = []

    async def boom(ctx: HopContext) -> bool:
        raise RuntimeError("authz down")

    res = await run_agent_graph(_spec(), "hi", runner=_runner(calls), hop_authorizer=boom)
    # Only the entry ran; every downstream hop denied (fail-closed).
    assert calls == ["ag-root"]
    assert res["results"]["a"]["denied"] is True
    assert res["results"]["b"]["denied"] is True


@pytest.mark.asyncio
async def test_hop_context_carries_identity():
    calls: list[str] = []
    seen: list[tuple] = []

    async def record(ctx: HopContext) -> bool:
        seen.append((ctx.from_node_id, ctx.from_agent_id, ctx.to_node_id, ctx.to_agent_id))
        return True

    await run_agent_graph(_spec(), "hi", runner=_runner(calls), hop_authorizer=record)
    assert ("root", "ag-root", "a", "ag-a") in seen
    assert ("root", "ag-root", "b", "ag-b") in seen
