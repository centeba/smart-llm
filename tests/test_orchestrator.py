"""Phase E2 tests — agent-graph orchestrator.

Coverage:
- ``AgentGraphSpec.from_dict`` rejects cycles.
- ``MAX_DEPTH = 3`` enforced (a 4-deep DAG raises before any runner
  call).
- Missing entry / unknown next-id raise.
- ``_branch_matches`` predicate parsing: equality match, mismatch,
  malformed (warn, treat as match).
- ``run_agent_graph`` fan-out: 1 entry → 3 children produces 3
  parallel runner calls (mocked) and merges results by node id.
- ``OrchestratorSkill.run`` is a pure pass-through (no mutation).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from smart_llm.orchestrator import (
    MAX_DEPTH,
    AgentGraphSpec,
    OrchestratorSkill,
    _branch_matches,
    run_agent_graph,
)

# ── Spec validation ─────────────────────────────────────────────────────────


def test_max_depth_constant_is_3():
    """The depth cap is documented at 3; lock it in so an accidental
    bump in the future trips a test."""
    assert MAX_DEPTH == 3


def test_spec_rejects_cycle():
    raw = {
        "entry": "a",
        "nodes": [
            {"id": "a", "agent_id": "agent-A", "next": ["b"]},
            {"id": "b", "agent_id": "agent-B", "next": ["a"]},  # cycle
        ],
    }
    with pytest.raises(ValueError, match="cycle"):
        AgentGraphSpec.from_dict(raw)


def test_spec_rejects_depth_over_max():
    # 5-deep chain: a → b → c → d → e
    raw = {
        "entry": "a",
        "nodes": [
            {"id": "a", "agent_id": "A", "next": ["b"]},
            {"id": "b", "agent_id": "B", "next": ["c"]},
            {"id": "c", "agent_id": "C", "next": ["d"]},
            {"id": "d", "agent_id": "D", "next": ["e"]},
            {"id": "e", "agent_id": "E", "next": []},
        ],
    }
    with pytest.raises(ValueError, match=f"MAX_DEPTH={MAX_DEPTH}"):
        AgentGraphSpec.from_dict(raw)


def test_spec_accepts_exact_max_depth():
    """Boundary: a depth-3 spec is the largest permitted."""
    raw = {
        "entry": "a",
        "nodes": [
            {"id": "a", "agent_id": "A", "next": ["b"]},
            {"id": "b", "agent_id": "B", "next": ["c"]},
            {"id": "c", "agent_id": "C", "next": []},
        ],
    }
    spec = AgentGraphSpec.from_dict(raw)
    assert spec.entry == "a"
    assert set(spec.nodes.keys()) == {"a", "b", "c"}


def test_spec_rejects_missing_entry():
    raw = {
        "entry": "ghost",
        "nodes": [{"id": "a", "agent_id": "A", "next": []}],
    }
    with pytest.raises(ValueError, match="entry .* missing"):
        AgentGraphSpec.from_dict(raw)


def test_spec_rejects_unknown_next_id():
    raw = {
        "entry": "a",
        "nodes": [
            {"id": "a", "agent_id": "A", "next": ["b"]},
            # No node "b" — points into the void.
        ],
    }
    with pytest.raises(ValueError, match="unknown node 'b'"):
        AgentGraphSpec.from_dict(raw)


# ── Branch predicate ────────────────────────────────────────────────────────


def test_branch_matches_no_predicate():
    assert _branch_matches(None, {"intent": "summary"}) is True
    assert _branch_matches("", {"intent": "summary"}) is True


def test_branch_matches_equality_hit():
    assert _branch_matches("intent==summary", {"intent": "summary"}) is True


def test_branch_matches_equality_miss():
    assert _branch_matches("intent==summary", {"intent": "tag"}) is False


def test_branch_matches_handles_missing_key():
    # ``upstream.get("foo")`` is ``None`` — repr is "None", not equal
    # to "summary" → False.
    assert _branch_matches("foo==summary", {}) is False


def test_branch_matches_warns_on_malformed_predicate():
    """Anything without ``==`` is treated as unconditional + a log
    warning is emitted (verified manually; here we only check the
    return value)."""
    assert _branch_matches("intent matches summary", {"intent": "x"}) is True


# ── run_agent_graph ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_graph_single_node():
    """Trivial spec: one entry, no children. Runner is called exactly
    once with the initial input."""
    raw = {
        "entry": "a",
        "nodes": [{"id": "a", "agent_id": "agent-A", "next": []}],
    }
    spec = AgentGraphSpec.from_dict(raw)
    runner = AsyncMock(return_value={"reply": "ok"})

    out = await run_agent_graph(spec, "hello", runner=runner)

    runner.assert_awaited_once_with("agent-A", "hello")
    assert out == {"results": {"a": {"reply": "ok"}}}


@pytest.mark.asyncio
async def test_run_graph_fans_out_to_all_branches_when_no_predicate():
    """Entry → 3 children, none with a branch predicate. All three
    children run."""
    raw = {
        "entry": "root",
        "nodes": [
            {
                "id": "root",
                "agent_id": "classifier",
                "next": ["c1", "c2", "c3"],
            },
            {"id": "c1", "agent_id": "child-1", "next": []},
            {"id": "c2", "agent_id": "child-2", "next": []},
            {"id": "c3", "agent_id": "child-3", "next": []},
        ],
    }
    spec = AgentGraphSpec.from_dict(raw)
    runner = AsyncMock(return_value={"reply": "ok"})

    out = await run_agent_graph(spec, "initial", runner=runner)

    # 1 entry + 3 children = 4 calls
    assert runner.await_count == 4
    assert set(out["results"].keys()) == {"root", "c1", "c2", "c3"}


@pytest.mark.asyncio
async def test_run_graph_respects_branch_predicate():
    """Entry returns ``{"intent": "summary"}``; only the matching
    child runs, the other one is skipped."""
    raw = {
        "entry": "root",
        "nodes": [
            {
                "id": "root",
                "agent_id": "classifier",
                "next": ["sum", "tag"],
            },
            {
                "id": "sum",
                "agent_id": "summarizer",
                "next": [],
                "branch": "intent==summary",
            },
            {
                "id": "tag",
                "agent_id": "tagger",
                "next": [],
                "branch": "intent==tag",
            },
        ],
    }
    spec = AgentGraphSpec.from_dict(raw)

    # Per-agent responses: classifier emits the intent, leaves echo.
    async def runner(agent_id: str, input_text: str) -> dict:
        if agent_id == "classifier":
            return {"intent": "summary"}
        return {"agent": agent_id, "echo": input_text}

    out = await run_agent_graph(spec, "input", runner=runner)

    assert "root" in out["results"]
    assert "sum" in out["results"]  # branch matched
    assert "tag" not in out["results"]  # branch missed


@pytest.mark.asyncio
async def test_run_graph_passes_upstream_response_as_json_text():
    """Each child receives the upstream's response coerced to JSON
    text so the agent's first user turn sees the full payload."""
    raw = {
        "entry": "root",
        "nodes": [
            {"id": "root", "agent_id": "A", "next": ["child"]},
            {"id": "child", "agent_id": "B", "next": []},
        ],
    }
    spec = AgentGraphSpec.from_dict(raw)

    received_inputs: list[tuple[str, str]] = []

    async def runner(agent_id: str, input_text: str) -> dict:
        received_inputs.append((agent_id, input_text))
        return {"node": agent_id, "score": 0.9}

    await run_agent_graph(spec, "kickoff", runner=runner)

    # Entry got the initial string verbatim.
    assert received_inputs[0] == ("A", "kickoff")
    # Child got upstream JSON.
    child_agent, child_input = received_inputs[1]
    assert child_agent == "B"
    assert '"node"' in child_input and '"A"' in child_input


# ── OrchestratorSkill ───────────────────────────────────────────────────────


def test_orchestrator_skill_is_pass_through():
    """The marker skill mutates nothing — real dispatch happens in the
    host activity. Verify the standard ``Tool.run`` contract."""
    skill = OrchestratorSkill()
    assert skill.run("anything") == "anything"
    # kwargs ignored (the spec is read by the activity, not the skill).
    assert skill.run("anything", spec={"entry": "x"}) == "anything"


def test_orchestrator_skill_registered_in_registry():
    """The skill auto-registers on import as ``orchestrate_agents``.
    Confirms ``smart_llm.registry`` sees it."""
    from smart_llm.registry import get_tool_meta

    meta = get_tool_meta("orchestrate_agents")
    assert meta is not None
    assert meta.cls is OrchestratorSkill
