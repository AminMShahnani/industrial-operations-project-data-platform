"""Typed application interface for other modules using the bounded expression engine."""

from operations.contracts import ServiceError
from operations.modules.forms.application.contracts import Expression, FormValues
from operations.modules.forms.domain.expressions import ExpressionError, Scalar, evaluate, inspect


def validate_condition(expression: Expression, field_keys: set[str]) -> None:
    try:
        inspect(expression.node(), field_keys)
        pending = [expression]
        while pending:
            item = pending.pop()
            if item.op == "context":
                raise ExpressionError("workflow_condition_requires_snapshot_fields")
            pending.extend(item.args)
    except ExpressionError as error:
        raise ServiceError(422, str(error)) from error


def condition_matches(expression: Expression, values: FormValues) -> bool:
    fields: dict[str, Scalar] = {}
    for key, value in values.fields.items():
        if value is None or isinstance(value, str | int | bool):
            fields[key] = value
    try:
        result = evaluate(expression.node(), fields, {})
        if not isinstance(result, bool):
            raise ExpressionError("workflow_condition_must_be_boolean")
        return result
    except ExpressionError as error:
        raise ServiceError(422, str(error)) from error
