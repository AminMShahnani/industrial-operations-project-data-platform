"""Bounded declarative evaluator. No source parsing or dynamic execution."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext

type Scalar = str | int | bool | None


class ExpressionError(ValueError):
    pass


@dataclass(frozen=True)
class Node:
    op: str
    value: Scalar = None
    key: str | None = None
    args: tuple[Node, ...] = ()


ARITY: dict[str, tuple[int, int]] = {
    "literal": (0, 0),
    "field": (0, 0),
    "context": (0, 0),
    "add": (2, 2),
    "subtract": (2, 2),
    "multiply": (2, 2),
    "divide": (2, 2),
    "eq": (2, 2),
    "ne": (2, 2),
    "lt": (2, 2),
    "lte": (2, 2),
    "gt": (2, 2),
    "gte": (2, 2),
    "and": (2, 20),
    "or": (2, 20),
    "not": (1, 1),
    "if": (3, 3),
    "coalesce": (1, 20),
    "concat": (1, 20),
    "length": (1, 1),
    "round": (2, 2),
}
CONTEXT_KEYS = frozenset({"current_user", "current_date", "current_datetime", "project", "shift"})


def inspect(node: Node, fields: set[str]) -> set[str]:
    count = 0
    dependencies: set[str] = set()

    def visit(item: Node, depth: int) -> None:
        nonlocal count
        count += 1
        if count > 200 or depth > 12 or item.op not in ARITY:
            raise ExpressionError("invalid_expression")
        minimum, maximum = ARITY[item.op]
        if not minimum <= len(item.args) <= maximum:
            raise ExpressionError("invalid_expression_arity")
        if item.op == "field":
            if item.key not in fields:
                raise ExpressionError("unknown_field_reference")
            assert item.key is not None
            dependencies.add(item.key)
        elif item.op == "context":
            if item.key not in CONTEXT_KEYS:
                raise ExpressionError("unknown_context_reference")
        elif item.key is not None:
            raise ExpressionError("invalid_expression_key")
        if item.op != "literal" and item.value is not None:
            raise ExpressionError("invalid_expression_value")
        if isinstance(item.value, str) and len(item.value) > 2000:
            raise ExpressionError("expression_literal_too_large")
        for child in item.args:
            visit(child, depth + 1)

    visit(node, 0)
    return dependencies


def dependency_order(graph: dict[str, set[str]]) -> list[str]:
    result: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise ExpressionError("formula_dependency_cycle")
        if key in visited:
            return
        visiting.add(key)
        for dependency in sorted(graph[key]):
            if dependency in graph:
                visit(dependency)
        visiting.remove(key)
        visited.add(key)
        result.append(key)

    for key in sorted(graph):
        visit(key)
    return result


def number(value: Scalar) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ExpressionError("numeric_operand_required")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ExpressionError("numeric_operand_required") from error
    if not result.is_finite() or abs(result) >= Decimal("1e18"):
        raise ExpressionError("numeric_operand_out_of_range")
    return result


def boolean(value: Scalar) -> bool:
    if not isinstance(value, bool):
        raise ExpressionError("boolean_operand_required")
    return value


def evaluate(node: Node, fields: dict[str, Scalar], context: dict[str, Scalar]) -> Scalar:
    # inspect is mandatory even on lazy branches: hidden malicious ASTs still deny.
    inspect(node, set(fields))

    def run(item: Node) -> Scalar:
        if item.op == "literal":
            return item.value
        if item.op == "field":
            return fields[item.key or ""]
        if item.op == "context":
            if item.key not in context or context[item.key] is None:
                raise ExpressionError("default_context_unavailable")
            return context[item.key]
        if item.op == "if":
            return run(item.args[1] if boolean(run(item.args[0])) else item.args[2])
        if item.op in {"and", "or"}:
            values = (boolean(run(child)) for child in item.args)
            return all(values) if item.op == "and" else any(values)
        if item.op == "coalesce":
            for child in item.args:
                value = run(child)
                if value is not None:
                    return value
            return None
        args = [run(child) for child in item.args]
        if item.op == "not":
            return not boolean(args[0])
        if item.op in {"eq", "ne"}:
            equal = type(args[0]) is type(args[1]) and args[0] == args[1]
            return equal if item.op == "eq" else not equal
        if item.op == "concat":
            if any(not isinstance(value, str) for value in args):
                raise ExpressionError("text_operand_required")
            output = "".join(str(value) for value in args)
            if len(output) > 2000:
                raise ExpressionError("expression_result_too_large")
            return output
        if item.op == "length":
            if not isinstance(args[0], str):
                raise ExpressionError("text_operand_required")
            return len(args[0])
        left, right = number(args[0]), number(args[1])
        if item.op == "lt":
            return left < right
        if item.op == "lte":
            return left <= right
        if item.op == "gt":
            return left > right
        if item.op == "gte":
            return left >= right
        try:
            with localcontext() as precision:
                precision.prec = 40
                if item.op == "add":
                    result = left + right
                elif item.op == "subtract":
                    result = left - right
                elif item.op == "multiply":
                    result = left * right
                elif item.op == "divide":
                    result = left / right
                elif item.op == "round":
                    if right != right.to_integral_value() or not 0 <= right <= 6:
                        raise ExpressionError("invalid_round_precision")
                    result = left.quantize(Decimal(1).scaleb(-int(right)))
                else:
                    raise ExpressionError("invalid_expression")
                if not result.is_finite() or abs(result) >= Decimal("1e18"):
                    raise ExpressionError("expression_result_out_of_range")
                return format(result.quantize(Decimal("0.000001")).normalize(), "f")
        except ArithmeticError as error:
            raise ExpressionError("invalid_arithmetic") from error

    return run(node)
