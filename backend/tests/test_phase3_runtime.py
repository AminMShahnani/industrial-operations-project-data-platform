from collections.abc import Mapping, Sequence

import pytest
from operations.modules.forms.application.contracts import FormDefinition, FormValues
from operations.modules.forms.application.runtime import compile_definition, runtime
from operations.modules.forms.domain.expressions import (
    ExpressionError,
    Node,
    dependency_order,
    evaluate,
    inspect,
)
from pydantic import ValidationError


def definition(fields: Sequence[Mapping[str, object]]) -> FormDefinition:
    return FormDefinition.model_validate(
        {"sections": [{"key": "main", "label": "Main", "components": fields}]}
    )


def test_bounded_ast_rejects_code_unknown_references_and_cycles() -> None:
    for node in (
        Node("eval"),
        Node("field", key="absent"),
        Node("context", key="password"),
        Node("add", args=(Node("literal", 1),)),
        Node("literal", "x" * 2001),
    ):
        with pytest.raises(ExpressionError):
            inspect(node, {"a"})
    deep = Node("literal", True)
    for _ in range(14):
        deep = Node("not", args=(deep,))
    with pytest.raises(ExpressionError):
        inspect(deep, set())
    with pytest.raises(ExpressionError, match="cycle"):
        dependency_order({"a": {"b"}, "b": {"a"}})
    assert dependency_order({"a": set(), "b": {"a"}}) == ["a", "b"]


def test_decimal_precision_lazy_branches_and_strict_boolean_operands() -> None:
    expression = Node(
        "add", args=(Node("literal", "99999999999999999.000001"), Node("literal", "0.000001"))
    )
    assert evaluate(expression, {}, {}) == "99999999999999999.000002"
    with pytest.raises(ExpressionError):
        evaluate(Node("divide", args=(Node("literal", 1), Node("literal", 0))), {}, {})
    safe = Node(
        "if", args=(Node("literal", True), Node("literal", "ok"), Node("context", key="shift"))
    )
    assert evaluate(safe, {}, {}) == "ok"
    with pytest.raises(ExpressionError):
        evaluate(Node("not", args=(Node("literal", 1),)), {}, {})


def test_publication_rejects_duplicate_keys_cycles_and_permission_leaks() -> None:
    base = {"key": "a", "kind": "integer", "label": "A"}
    for fields in (
        [base, base],
        [
            {
                "key": "a",
                "kind": "calculated",
                "label": "A",
                "formula": {"op": "field", "key": "b"},
            },
            {
                "key": "b",
                "kind": "calculated",
                "label": "B",
                "formula": {"op": "field", "key": "a"},
            },
        ],
        [
            {**base, "permissions": {"read": "manager"}},
            {
                "key": "b",
                "kind": "calculated",
                "label": "B",
                "formula": {"op": "field", "key": "a"},
            },
        ],
    ):
        with pytest.raises(ExpressionError):
            compile_definition(definition(fields))


def test_runtime_condition_defaults_formula_and_authoritative_values() -> None:
    schema = definition(
        [
            {"key": "quantity", "kind": "integer", "label": "Quantity", "required": True},
            {
                "key": "double",
                "kind": "calculated",
                "label": "Double",
                "formula": {
                    "op": "multiply",
                    "args": [{"op": "field", "key": "quantity"}, {"op": "literal", "value": 2}],
                },
            },
            {
                "key": "today",
                "kind": "date",
                "label": "Today",
                "default": {"op": "context", "key": "current_date"},
            },
            {
                "key": "notes",
                "kind": "textarea",
                "label": "Notes",
                "required_when": {
                    "op": "gt",
                    "args": [{"op": "field", "key": "quantity"}, {"op": "literal", "value": 3}],
                },
            },
        ]
    )
    result = runtime(
        schema,
        FormValues(fields={"quantity": 4}),
        {"current_date": "2026-10-05"},
        True,
        False,
        True,
        True,
    )
    assert result.values.fields["double"] == "8"
    assert result.values.fields["today"] == "2026-10-05"
    assert [(issue.key, issue.code) for issue in result.issues] == [("notes", "required")]
    result = runtime(
        schema,
        FormValues(fields={"quantity": True, "double": "99", "surprise": "x"}),
        {},
        True,
        False,
        False,
        True,
    )
    assert {issue.code for issue in result.issues} >= {
        "invalid_value",
        "unknown_component",
        "calculated_value_is_server_owned",
    }


@pytest.mark.parametrize(
    "kind,value",
    [
        ("integer", True),
        ("decimal", "NaN"),
        ("decimal", "1e3"),
        ("datetime", "2026-10-05T12:00:00"),
        ("date", "20261005"),
        ("time", "bad"),
        ("boolean", "true"),
        ("user", "bad-id"),
        ("select", "other"),
    ],
)
def test_invalid_component_values(kind: str, value: object) -> None:
    field: dict[str, object] = {"key": "a", "kind": kind, "label": "A"}
    if kind == "select":
        field["choices"] = ["one"]
    result = runtime(
        definition([field]),
        FormValues.model_validate({"fields": {"a": value}}),
        {},
        True,
        False,
        False,
        True,
    )
    assert result.issues[0].code == "invalid_value"


def test_repeating_rows_permissions_and_payload_bounds() -> None:
    schema = definition(
        [
            {
                "key": "items",
                "kind": "table",
                "label": "Items",
                "children": [
                    {"key": "count", "kind": "integer", "label": "Count", "required": True},
                    {
                        "key": "secret",
                        "kind": "text",
                        "label": "Secret",
                        "permissions": {"read": "manager", "write": "manager"},
                    },
                ],
            }
        ]
    )
    result = runtime(
        schema,
        FormValues.model_validate(
            {"fields": {"items": [{"count": "wrong", "secret": "injected"}]}}
        ),
        {},
        True,
        False,
        False,
        True,
    )
    assert {issue.code for issue in result.issues} == {"invalid_value", "component_not_available"}
    with pytest.raises(ValidationError):
        FormValues.model_validate({"fields": {"items": [{"count": 1}] * 101}})
    with pytest.raises(ValidationError):
        FormValues(fields={"a": "x" * 2001})


def test_readonly_values_are_preserved_hidden_formulas_recomputed_and_publicly_redacted() -> None:
    from operations.modules.forms.application.runtime import public_runtime

    schema = definition(
        [
            {"key": "count", "kind": "integer", "label": "Count"},
            {
                "key": "fixed",
                "kind": "text",
                "label": "Fixed",
                "required": True,
                "permissions": {"read": "all", "write": "manager"},
            },
            {
                "key": "secret",
                "kind": "calculated",
                "label": "Secret",
                "permissions": {"read": "manager"},
                "formula": {
                    "op": "multiply",
                    "args": [{"op": "field", "key": "count"}, {"op": "literal", "value": 2}],
                },
            },
        ]
    )
    stored = FormValues(fields={"count": 1, "fixed": "Governed", "secret": "2"})
    result = runtime(schema, FormValues(fields={"count": 3}), {}, True, False, False, True, stored)
    assert result.issues == []
    assert result.values.fields["fixed"] == "Governed" and result.values.fields["secret"] == "6"
    assert "secret" not in public_runtime(result).values.fields
    denied = runtime(
        schema,
        FormValues(fields={"count": 3, "fixed": "Changed"}),
        {},
        True,
        False,
        False,
        True,
        stored,
    )
    assert any(issue.code == "component_write_denied" for issue in denied.issues)
