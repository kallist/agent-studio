from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from app.domain.errors import ToolExecutionError, ToolValidationError

BinaryOperator = Callable[[Decimal, Decimal], Decimal]

_OPERATORS: dict[type[ast.operator], BinaryOperator] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def calculate(expression: str) -> str:
    if not expression.strip():
        raise ToolValidationError("Expression must not be empty.")
    if len(expression) > 200:
        raise ToolValidationError("Expression exceeds the 200 character limit.")

    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolValidationError("Expression is not valid arithmetic.") from exc

    try:
        result = _evaluate(parsed.body, depth=0)
    except (InvalidOperation, OverflowError) as exc:
        raise ToolExecutionError("Expression could not be evaluated.") from exc

    if not result.is_finite():
        raise ToolExecutionError("Expression produced a non-finite result.")
    normalized = result.normalize()
    return format(normalized, "f")


def _evaluate(node: ast.AST, depth: int) -> Decimal:
    if depth > 32:
        raise ToolValidationError("Expression is too deeply nested.")
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int | float)
        and not isinstance(node.value, bool)
    ):
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
        value = _evaluate(node.operand, depth + 1)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        left = _evaluate(node.left, depth + 1)
        right = _evaluate(node.right, depth + 1)
        if isinstance(node.op, ast.Div) and right == 0:
            raise ToolExecutionError("Division by zero is not allowed.")
        return _OPERATORS[type(node.op)](left, right)
    raise ToolValidationError("Only numbers, +, -, *, /, unary signs, and parentheses are allowed.")
