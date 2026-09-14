"""`calculate` builtin (G5) — safe arithmetic, no eval.

A domain-agnostic helper attachable to any agent. Evaluates a math expression
via a restricted AST walk (operators + a whitelist of math functions/constants);
it never calls ``eval``/``exec`` and rejects names, attributes, comprehensions,
or anything else.
"""

import ast
import math
import operator
from collections.abc import Callable
from typing import Any, cast

from pydantic import BaseModel, Field

from smart_llm.base import ActionTool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool

_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCS: dict[str, Callable[..., Any]] = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "pow": pow,
    "floor": math.floor,
    "ceil": math.ceil,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def safe_calculate(expression: str) -> float | int:
    """Evaluate an arithmetic expression safely. Raises ValueError on anything
    outside the allowed operator/function whitelist."""

    def _eval(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS
            and not node.keywords
        ):
            return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
        raise ValueError("unsupported expression element")

    tree = ast.parse(expression, mode="eval")
    return cast("float | int", _eval(tree.body))


class CalculateArgs(BaseModel):
    expression: str = Field(
        ..., description="A math expression, e.g. '2*(3+4)/sqrt(2)'."
    )


class CalculateTool(ActionTool):
    args_model = CalculateArgs
    read_only = True
    risk = "read"

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        try:
            return {"result": safe_calculate(cast(CalculateArgs, args).expression)}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"could not evaluate expression: {exc}"}


register_tool(
    "calculate",
    CalculateTool,
    label="Calculate",
    description="Evaluate an arithmetic expression safely (operators + common "
    "math functions; no code execution).",
    modality=MODALITY_TEXT,
    risk="read",
)
