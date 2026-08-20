import pytest

from app.domain.errors import ToolExecutionError, ToolValidationError
from app.tools.calculator import calculate


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2", "3"),
        ("9 - 12", "-3"),
        ("128 * 37 + 456", "5192"),
        ("(2 + 3) * 4", "20"),
        ("10 / 4", "2.5"),
        ("-5 + 2", "-3"),
    ],
)
def test_calculate_valid_expression(expression: str, expected: str) -> None:
    assert calculate(expression) == expected


def test_calculate_rejects_division_by_zero() -> None:
    with pytest.raises(ToolExecutionError, match="Division by zero"):
        calculate("1 / 0")


@pytest.mark.parametrize(
    "expression",
    [
        "not arithmetic",
        "__import__('os').system('echo unsafe')",
        "value + 1",
        "(1).real",
        "2 ** 8",
        "[1, 2]",
        "open('secret.txt')",
        "lambda: 1",
        "sum([1, 2])",
        "[value for value in [1, 2]]",
        "{'key': 1}",
        "True + 1",
    ],
)
def test_calculate_rejects_invalid_or_unsafe_input(expression: str) -> None:
    with pytest.raises(ToolValidationError):
        calculate(expression)
