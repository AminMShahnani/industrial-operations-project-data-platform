import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import cast

from operations.modules.forms.application.contracts import (
    Component,
    FormDefinition,
    FormValues,
    RuntimeIssue,
    RuntimeResult,
    Value,
)
from operations.modules.forms.domain.expressions import (
    ExpressionError,
    Scalar,
    boolean,
    dependency_order,
    evaluate,
    inspect,
)


def components(definition: FormDefinition) -> list[Component]:
    return [component for section in definition.sections for component in section.components]


def compile_fields(fields: list[Component]) -> list[str]:
    keys = {field.key for field in fields}
    if len(keys) != len(fields) or len(keys) > 100:
        raise ExpressionError("duplicate_or_excessive_component_keys")
    graph: dict[str, set[str]] = {}
    policies = {field.key: field.permissions for field in fields}
    for field in fields:
        dependencies: set[str] = set()
        if (
            field.default
            and field.default.op == "literal"
            and not valid_value(field, field.default.value)
        ):
            raise ExpressionError("invalid_static_default")
        for expression in (
            field.default,
            field.formula,
            field.visible_when,
            field.required_when,
            field.validation.condition,
        ):
            if expression:
                references = inspect(expression.node(), keys)
                for key in references:
                    source = policies[key].read
                    if source != "all" and field.permissions.read != source:
                        raise ExpressionError("expression_permission_leak")
                dependencies.update(
                    references
                    - ({field.key} if expression is field.validation.condition else set())
                )
        # Conditions participate too: visibility/required cycles are equally invalid.
        graph[field.key] = dependencies
        if field.children:
            compile_fields(field.children)
    return dependency_order(graph)


def compile_definition(definition: FormDefinition) -> list[str]:
    sections = [section.key for section in definition.sections]
    if len(set(sections)) != len(sections):
        raise ExpressionError("duplicate_section_keys")
    if any(section.references for section in definition.sections):
        raise ExpressionError("unresolved_library_reference")
    fields = components(definition)
    if not fields:
        raise ExpressionError("empty_form_definition")
    return compile_fields(fields)


def valid_value(field: Component, value: Value) -> bool:
    kind = field.kind
    if value is None:
        return True
    if kind == "calculated":
        return (isinstance(value, str) and len(value) <= field.validation.max_length) or type(
            value
        ) in {int, bool}
    if kind in {"text", "textarea", "select", "radio", "display", "signature"}:
        if not isinstance(value, str) or len(value) > field.validation.max_length:
            return False
        if field.validation.min_length is not None and len(value) < field.validation.min_length:
            return False
        return kind not in {"select", "radio"} or value in field.choices
    if kind == "multi_select":
        return (
            isinstance(value, list)
            and len(value) <= 100
            and all(isinstance(item, str) and item in field.choices for item in value)
            and len(set(str(item) for item in value)) == len(value)
        )
    if kind == "integer":
        if type(value) is not int or not -(2**63) <= value < 2**63:
            return False
    elif kind == "decimal":
        if not isinstance(value, str) or not re.fullmatch(
            r"-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,6})?", value
        ):
            return False
    elif kind == "boolean":
        return type(value) is bool
    elif kind in {"date", "datetime", "time"}:
        if not isinstance(value, str):
            return False
        try:
            if kind == "date":
                return date.fromisoformat(value).isoformat() == value
            if kind == "datetime":
                parsed = datetime.fromisoformat(value)
                return parsed.utcoffset() is not None
            return time.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    elif kind in {"user", "department", "project", "master_data", "file", "image"}:
        if not isinstance(value, str):
            return False
        from uuid import UUID

        try:
            return str(UUID(value)) == value
        except ValueError:
            return False
    elif kind in {"table", "repeating_group"}:
        return (
            isinstance(value, list)
            and len(value) <= field.validation.max_rows
            and all(isinstance(row, dict) for row in value)
        )
    else:
        return False
    numeric = Decimal(str(value))
    return (field.validation.minimum is None or numeric >= Decimal(field.validation.minimum)) and (
        field.validation.maximum is None or numeric <= Decimal(field.validation.maximum)
    )


def runtime(
    definition: FormDefinition,
    supplied: FormValues,
    context: dict[str, Scalar],
    owner: bool,
    manager: bool,
    apply_defaults: bool,
    complete: bool,
    preserved: FormValues | None = None,
) -> RuntimeResult:
    compile_definition(definition)
    issues: list[RuntimeIssue] = []
    visible: list[str] = []
    required: list[str] = []

    def issue(key: str, code: str) -> None:
        issues.append(RuntimeIssue(key=key, code=code))

    def permitted(policy: str) -> bool:
        return policy == "all" or (policy == "owner" and owner) or (policy == "manager" and manager)

    def process(
        fields: list[Component], values: dict[str, Value], prefix: str, stored: dict[str, Value]
    ) -> dict[str, Value]:
        by_key = {field.key: field for field in fields}
        result: dict[str, Value] = {key: stored.get(key) for key in by_key}
        for key in values:
            if key not in by_key:
                issue(prefix + key, "unknown_component")
        for key in compile_fields(fields):
            field = by_key[key]
            path = prefix + key
            scalar: dict[str, Scalar] = {
                name: value if isinstance(value, str | int | bool) or value is None else None
                for name, value in result.items()
            }
            # Raw inputs are available to expressions independent of component ordering.
            scalar.update(
                {
                    name: value
                    for name, value in values.items()
                    if name in by_key
                    and permitted(by_key[name].permissions.write)
                    and (isinstance(value, str | int | bool) or value is None)
                }
            )
            # Derived/default values must take precedence over caller attempts.
            for name in result:
                if result[name] is not None and isinstance(result[name], str | int | bool):
                    scalar[name] = result[name]  # type: ignore[assignment]
            value = values.get(key)
            try:
                shown = field.visible_when is None or boolean(
                    evaluate(field.visible_when.node(), scalar, context)
                )
                can_read = permitted(field.permissions.read)
                if not shown or not can_read:
                    if key in values and values[key] is not None:
                        issue(path, "component_not_available")
                    if not shown:
                        result[key] = None
                    elif field.formula:
                        result[key] = evaluate(field.formula.node(), scalar, context)
                    continue
                visible.append(path)
                needed = field.required or (
                    field.required_when is not None
                    and boolean(evaluate(field.required_when.node(), scalar, context))
                )
                if needed:
                    required.append(path)
                if field.kind == "display":
                    if value is not None:
                        issue(path, "read_only_component")
                    continue
                if field.formula:
                    if key in values and value is not None:
                        issue(path, "calculated_value_is_server_owned")
                    value = evaluate(field.formula.node(), scalar, context)
                elif not permitted(field.permissions.write):
                    if value is not None:
                        issue(path, "component_write_denied")
                    value = stored.get(key)
                if value is None and field.default and apply_defaults:
                    value = evaluate(field.default.node(), scalar, context)
                if (
                    value is None
                    and field.source
                    and field.source.previous_approved_key
                    and apply_defaults
                ):
                    issue(path, "approved_default_unavailable")
                if complete and needed and (value is None or value == "" or value == []):
                    issue(path, "required")
                if not valid_value(field, value):
                    issue(path, "invalid_value")
                    continue
                if field.children and isinstance(value, list):
                    rows: list[dict[str, Scalar | list[str]]] = []
                    for index, row in enumerate(value):
                        if isinstance(row, dict):
                            stored_rows = stored.get(key)
                            stored_row = (
                                stored_rows[index]
                                if isinstance(stored_rows, list) and index < len(stored_rows)
                                else None
                            )
                            nested = process(
                                field.children,
                                row,
                                f"{path}[{index}].",
                                cast(dict[str, Value], stored_row)
                                if isinstance(stored_row, dict)
                                else {},
                            )
                            rows.append(cast(dict[str, Scalar | list[str]], nested))
                    value = rows
                scalar[key] = (
                    value if isinstance(value, str | int | bool) or value is None else None
                )
                if (
                    field.validation.condition
                    and value is not None
                    and not boolean(evaluate(field.validation.condition.node(), scalar, context))
                ):
                    issue(path, "validation_condition_failed")
                result[key] = value
            except ExpressionError as error:
                issue(path, str(error))
        return result

    result = process(
        components(definition), supplied.fields, "", preserved.fields if preserved else {}
    )
    return RuntimeResult(
        values=FormValues(fields=result),
        visible_keys=visible,
        required_keys=required,
        issues=issues,
    )


def public_runtime(result: RuntimeResult) -> RuntimeResult:
    visible = set(result.visible_keys)

    def filter_values(values: dict[str, Value], prefix: str) -> dict[str, Value]:
        output: dict[str, Value] = {}
        for key, value in values.items():
            path = prefix + key
            if path not in visible:
                continue
            if isinstance(value, list) and value and isinstance(value[0], dict):
                value = [
                    cast(
                        dict[str, Scalar | list[str]],
                        filter_values(cast(dict[str, Value], row), f"{path}[{index}]."),
                    )
                    for index, row in enumerate(value)
                    if isinstance(row, dict)
                ]
            output[key] = value
        return output

    return result.model_copy(
        update={"values": FormValues(fields=filter_values(result.values.fields, ""))}
    )
