"""Agent-eval harness — deterministic checks, LLM judge, markdown report."""

import pytest

from smart_llm.base import LLMResponse
from smart_llm.evals import (
    AgentRun,
    Contains,
    Equals,
    EvalCase,
    JsonSchemaValid,
    LLMJudge,
    ToolCalled,
    agent_runner,
    run_evals,
    to_markdown,
)


class _FakeAgent:
    """Minimal stand-in for smart_llm.Agent — returns fixed response data."""

    def __init__(self, data):
        self._data = data

    async def analyze(self, input_text, **_):
        return LLMResponse(
            data=self._data,
            provider="fake",
            metadata={"usage": {"input_tokens": 1, "output_tokens": 1}},
        )


@pytest.mark.asyncio
async def test_deterministic_evaluators_and_report():
    cases = [EvalCase(input="say hello", expected="hello", id="c1")]

    async def runner(case):
        return AgentRun(output="hello", tools_called=["search"])

    results = await run_evals(
        cases, runner, [Equals(), Contains("ell"), ToolCalled("search")]
    )
    assert results[0].passed
    md = to_markdown(results)
    assert "1/1 passed" in md
    assert "| Case |" in md


@pytest.mark.asyncio
async def test_failing_check_marks_result_failed():
    cases = [EvalCase(input="x", id="c1")]

    async def runner(case):
        return AgentRun(output="world", tools_called=[])

    results = await run_evals(cases, runner, [Contains("hello"), ToolCalled("search")])
    assert not results[0].passed
    assert "0/1 passed" in to_markdown(results)


@pytest.mark.asyncio
async def test_agent_runner_with_contains():
    agent = _FakeAgent({"content": "The capital of France is Paris."})
    runner = agent_runner(lambda case: agent)
    results = await run_evals([EvalCase(input="capital?", id="c1")], runner, [Contains("Paris")])
    assert results[0].passed
    assert results[0].run.usage == {"input_tokens": 1, "output_tokens": 1}


@pytest.mark.asyncio
async def test_llm_judge_scores_with_neutral_agent():
    judge = _FakeAgent({"score": 0.9, "reason": "accurate"})
    agent = _FakeAgent({"content": "Paris."})
    runner = agent_runner(lambda case: agent)
    results = await run_evals(
        [EvalCase(input="capital of France?", id="c1")],
        runner,
        [LLMJudge("Is it factually correct?", judge, threshold=0.7)],
    )
    r = results[0]
    assert r.passed
    judge_check = next(c for c in r.checks if c.name == "llm_judge")
    assert judge_check.score == 0.9
    # The judge score renders in the report.
    assert "0.90" in to_markdown(results)


@pytest.mark.asyncio
async def test_json_schema_evaluator():
    from pydantic import BaseModel

    class _Out(BaseModel):
        answer: str

    async def runner(case):
        return AgentRun(output="", data={"answer": "yes"})

    good = await run_evals([EvalCase(input="q")], runner, [JsonSchemaValid(_Out)])
    assert good[0].passed

    async def bad_runner(case):
        return AgentRun(output="", data={"wrong": 1})

    bad = await run_evals([EvalCase(input="q")], bad_runner, [JsonSchemaValid(_Out)])
    assert not bad[0].passed


@pytest.mark.asyncio
async def test_runner_error_is_captured_not_raised():
    async def boom(case):
        raise RuntimeError("agent exploded")

    results = await run_evals([EvalCase(input="q", id="c1")], boom, [Contains("x")])
    assert results[0].run.error == "agent exploded"
    assert not results[0].passed
