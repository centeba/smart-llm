"""Lightweight, provider-neutral agent-evaluation harness.

Closes a gap from the Strands comparison: we had unit tests but no way to score
an agent's output / trajectory / tool-use over a dataset. This is a small
harness — not a service — for CI or ad-hoc quality checks:

    cases = [EvalCase(input="capital of France?", expected="Paris")]
    results = await run_evals(cases, agent_runner(build_agent), [
        Contains("Paris"),
        LLMJudge("Is the answer factually correct?", judge_agent),
    ])
    print(to_markdown(results))

Unlike Strands' evals SDK (whose judge defaults to Bedrock/Claude), the LLM
judge here is any ``smart_llm.Agent`` — provider-neutral.
"""

from .evaluators import (
    Contains,
    Equals,
    Evaluator,
    JsonSchemaValid,
    LLMJudge,
    ToolCalled,
)
from .report import to_markdown
from .runner import (
    AgentRun,
    EvalCase,
    EvalCheck,
    EvalResult,
    agent_runner,
    run_evals,
)

__all__ = [
    "AgentRun",
    "Contains",
    "Equals",
    "EvalCase",
    "EvalCheck",
    "EvalResult",
    "Evaluator",
    "JsonSchemaValid",
    "LLMJudge",
    "ToolCalled",
    "agent_runner",
    "run_evals",
    "to_markdown",
]
