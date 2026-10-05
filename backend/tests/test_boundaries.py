import ast
import sys
from pathlib import Path

MODULES = Path("backend/src/operations/modules")
LAYERS = {"domain", "application", "infrastructure", "api"}


def boundary_errors(source: str, module: str, layer: str) -> list[str]:
    errors: list[str] = []
    for node in ast.walk(ast.parse(source)):
        imports: list[str] = []
        if isinstance(node, ast.Import):
            imports = [name.name for name in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                errors.append("Use absolute module imports so boundaries remain explicit")
            imports = [node.module or ""]
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"__import__", "eval", "exec"}
        ):
            errors.append("Dynamic imports and arbitrary execution are prohibited")
        for target in imports:
            parts = target.split(".")
            if target.startswith("importlib"):
                errors.append("Dynamic imports are prohibited")
            if layer == "domain":
                if parts[0] not in sys.stdlib_module_names and parts[0] != "operations":
                    errors.append("Domain imports must be standard library or own domain")
                if target.startswith(("fastapi", "starlette", "sqlalchemy", "psycopg", "pydantic")):
                    errors.append("Domain cannot depend on HTTP, ORM or boundary frameworks")
                if target.startswith("operations.") and not target.startswith(
                    f"operations.modules.{module}.domain"
                ):
                    errors.append("Domain may only import its own domain")
            if target.startswith("operations.modules.") and len(parts) >= 4:
                other_module, other_layer = parts[2:4]
                if other_module != module and other_layer != "application":
                    errors.append("Cross-module imports must use application interfaces")
                if layer == "application" and other_layer in {"infrastructure", "api"}:
                    errors.append("Application cannot import infrastructure or API")
            elif target.startswith("operations.modules."):
                errors.append("Import an explicit module layer, not a module root")
            if layer == "application" and target.startswith("operations.platform"):
                errors.append("Application contracts cannot depend on technical infrastructure")
    return errors


def test_module_boundaries() -> None:
    for path in MODULES.rglob("*.py"):
        parts = path.relative_to(MODULES).parts
        if len(parts) >= 3 and parts[1] in LAYERS:
            assert not boundary_errors(path.read_text(encoding="utf-8-sig"), parts[0], parts[1]), (
                path
            )


def test_guard_detects_forbidden_imports() -> None:
    assert boundary_errors("from sqlalchemy import select", "forms", "domain")
    assert boundary_errors(
        "from operations.modules.projects.infrastructure import repo", "forms", "application"
    )
    assert boundary_errors(
        "from operations.modules.forms.infrastructure import repo", "forms", "application"
    )
    assert boundary_errors("import importlib", "forms", "domain")
    assert not boundary_errors(
        "from operations.modules.projects.application import contracts", "forms", "application"
    )
