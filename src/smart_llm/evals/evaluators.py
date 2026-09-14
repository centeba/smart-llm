"""Evaluators — deterministic checks + a provider-neutral LLM judge.

Each evaluator implements ``async evaluate(case, run) -> EvalCheck``. Deterministic
ones need no model; :class:`LLMJudge` scores with any ``smart_llm.Agent``.
"""

from typing import Any, Protocol, runtime_checkable

from .runner import AgentRun, EvalCase, EvalCheck


@runtime_checkable
class Evaluator(Protocol):
    name: str

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalCheck: ...


class Equals:
    """Pass when a run field exactly equals the expected value (defaults to the
    case's ``expected``)."""

    name = "equals"

    def __init__(self, expected: Any = None, *, field: str = "output"):
        self._expected = expected
        self._field = field

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalCheck:
        expected = self._expected if self._expected is not None else case.expected
        actual = getattr(run, self._field, None)
        ok = actual == expected
        return EvalCheck(self.name, ok, 1.0 if ok else 0.0, f"{actual!r} == {expected!r}")


class Contains:
    """Pass when the output text contains ``needle``."""

    name = "contains"

    def __init__(self, needle: str, *, case_sensitive: bool = True):
        self._needle = needle
        self._cs = case_sensitive

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalCheck:
        output = run.output or ""
        if self._cs:
            ok = self._needle in output
        else:
            ok = self._needle.lower() in output.lower()
        return EvalCheck(self.name, ok, 1.0 if ok else 0.0, f"{self._needle!r} in output")


class ToolCalled:
    """Pass when the run's trajectory called ``tool_name``."""

    name = "tool_called"

    def __init__(self, tool_name: str):
        self._tool = tool_name

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalCheck:
        ok = self._tool in (run.tools_called or [])
        return EvalCheck(self.name, ok, 1.0 if ok else 0.0, f"{self._tool} in {run.tools_called}")


class JsonSchemaValid:
    """Pass when the output validates against a pydantic model."""

    name = "json_schema_valid"

    def __init__(self, model: Any):
        self._model = model

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalCheck:
        payload = run.data if run.data is not None else run.output
        try:
            if isinstance(payload, (dict, list)):
                self._model.model_validate(payload)
            else:
                self._model.model_validate_json(payload)
            return EvalCheck(self.name, True, 1.0, "valid")
        except Exception as exc:  # noqa: BLE001
            return EvalCheck(self.name, False, 0.0, str(exc))


class LLMJudge:
    """LLM-as-judge: score the output against a rubric with a judge agent.

    ``judge`` is any ``smart_llm.Agent`` (provider-neutral — not Bedrock-locked).
    The judge is asked to return ``{"score": 0..1, "reason": str}``; the check
    passes when ``score >= threshold``.
    """

    name = "llm_judge"

    def __init__(self, rubric: str, judge: Any, *, threshold: float = 0.7):
        self._rubric = rubric
        self._judge = judge
        self._threshold = threshold

    async def evaluate(self, case: EvalCase, run: AgentRun) -> EvalCheck:
        prompt = (
            f"You are grading an AI agent's output against a rubric.\n"
            f"Rubric: {self._rubric}\n\n"
            f"User input:\n{case.input}\n\n"
            f"Agent output:\n{run.output}\n\n"
            'Return JSON: {"score": <0..1 float>, "reason": "<short>"}.'
        )
        resp = await self._judge.analyze(prompt)
        data = getattr(resp, "data", None)
        data = data if isinstance(data, dict) else {}
        try:
            score = float(data.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        ok = score >= self._threshold
        return EvalCheck(self.name, ok, score, str(data.get("reason", "")))
