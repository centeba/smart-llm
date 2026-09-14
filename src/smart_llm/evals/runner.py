"""Eval data model + runner.

A ``runner`` is any ``async (EvalCase) -> AgentRun``; the harness stays neutral
about *how* an agent is run (single response, tool loop, streaming) — the caller
supplies the runner and, if the agent uses tools, populates ``tools_called``.
:func:`agent_runner` is the convenience runner for a single-response agent.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalCase:
    """One evaluation input (+ optional expected value / metadata)."""

    input: str
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str | None = None


@dataclass
class AgentRun:
    """What a runner captured for one case."""

    output: str = ""
    data: Any = None
    tools_called: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class EvalCheck:
    """One evaluator's verdict on one run."""

    name: str
    passed: bool
    score: float | None = None
    detail: str = ""


@dataclass
class EvalResult:
    case: EvalCase
    run: AgentRun
    checks: list[EvalCheck]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)


# An evaluator: async (case, run) -> EvalCheck (see evaluators.py for the
# Protocol). Kept as a duck-typed callable object here to avoid an import cycle.


async def run_evals(
    cases: Sequence[EvalCase],
    runner: Callable[[EvalCase], Awaitable[AgentRun]],
    evaluators: Sequence[Any],
    *,
    concurrency: int = 4,
) -> list[EvalResult]:
    """Run each case through ``runner`` and apply every evaluator.

    Runner errors are captured on ``AgentRun.error`` (not raised) so one bad case
    doesn't abort the suite; an evaluator that raises becomes a failed check.
    Cases run concurrently up to ``concurrency``.
    """
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(case: EvalCase) -> EvalResult:
        async with sem:
            try:
                run = await runner(case)
            except Exception as exc:  # noqa: BLE001 — capture, don't abort suite
                run = AgentRun(error=str(exc))
            checks: list[EvalCheck] = []
            for ev in evaluators:
                try:
                    checks.append(await ev.evaluate(case, run))
                except Exception as exc:  # noqa: BLE001
                    checks.append(
                        EvalCheck(
                            getattr(ev, "name", type(ev).__name__),
                            passed=False,
                            score=0.0,
                            detail=f"evaluator error: {exc}",
                        )
                    )
            return EvalResult(case=case, run=run, checks=checks)

    return list(await asyncio.gather(*[_one(c) for c in cases]))


def agent_runner(
    agent_factory: Callable[[EvalCase], Any],
) -> Callable[[EvalCase], Awaitable[AgentRun]]:
    """A runner that builds an agent per case and runs a single ``analyze``.

    ``agent_factory(case)`` returns a ``smart_llm.Agent`` (or anything with an
    async ``analyze(input)`` returning an ``LLMResponse``). For tool-using agents
    that need trajectory capture, write a custom runner that records
    ``tools_called``.
    """

    async def _run(case: EvalCase) -> AgentRun:
        agent = agent_factory(case)
        resp = await agent.analyze(case.input)
        data = getattr(resp, "data", None)
        output = data.get("content") if isinstance(data, dict) else data
        usage = (getattr(resp, "metadata", None) or {}).get("usage", {}) or {}
        return AgentRun(output=str(output or ""), data=data, usage=usage)

    return _run
