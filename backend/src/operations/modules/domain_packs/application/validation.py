"""Safe package-directory validation for the Domain Pack SDK."""

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import Field, ValidationError
from semantic_version import Version  # type: ignore[import-untyped]
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken

from operations.contracts import Command
from operations.modules.domain_packs.application.manifest import PackManifest
from operations.modules.domain_packs.application.migrations import (
    MigrationOperation,
    PackMigrationFile,
)

MANIFEST_NAMES = ("pack.yaml", "pack.yml")
MAX_MANIFEST_BYTES = 64 * 1024
MAX_CONTENT_BYTES = 4 * 1024 * 1024
MAX_PACKAGE_BYTES = 20 * 1024 * 1024
MAX_PACKAGE_FILES = 1000
MAX_PACKAGE_ENTRIES = 2000
MAX_PATH_DEPTH = 16


class PackValidationIssue(Command):
    code: str
    path: str | None = None
    message: str


class PackValidationResult(Command):
    valid: bool
    manifest: PackManifest | None = None
    package_sha256: str | None = None
    content_file_count: int = 0
    content_bytes: int = 0
    migration_operations: list[MigrationOperation] = Field(default_factory=list)
    issues: list[PackValidationIssue]


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader, node: MappingNode, deep: bool = False
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "mapping keys must be scalar values",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _load_yaml(path: Path, max_bytes: int) -> object:
    if path.stat().st_size > max_bytes:
        raise ValueError("YAML document exceeds the allowed size")
    with path.open("rb") as source:
        raw = source.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("YAML document exceeds the allowed size")
    text = raw.decode("utf-8")
    for token in yaml.scan(text, Loader=_UniqueKeySafeLoader):
        if isinstance(token, (AliasToken, AnchorToken)):
            raise ValueError("YAML anchors and aliases are not allowed")
    return yaml.load(text, Loader=_UniqueKeySafeLoader)


def _load_json(path: Path, max_bytes: int) -> object:
    if path.stat().st_size > max_bytes:
        raise ValueError("JSON document exceeds the allowed size")
    with path.open("rb") as source:
        raw = source.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("JSON document exceeds the allowed size")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("JSON document has a duplicate object key")
            result[key] = value
        return result

    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)


def _schema_issues(error: ValidationError) -> list[PackValidationIssue]:
    return [
        PackValidationIssue(
            code="manifest.invalid",
            path="pack.yaml",
            message=f"{'.'.join(str(item) for item in issue['loc'])}: {issue['msg']}",
        )
        for issue in error.errors(include_input=False)
    ]


def validate_pack_directory(
    directory: Path, *, core_version: str | None = None
) -> PackValidationResult:
    """Validate a local package without loading executable code or following links."""
    issues: list[PackValidationIssue] = []
    if directory.is_symlink() or not directory.is_dir():
        return PackValidationResult(
            valid=False,
            issues=[
                PackValidationIssue(
                    code="package.invalid_root",
                    message="Package root must be an existing non-symlink directory",
                )
            ],
        )

    root = directory.resolve()
    manifest_path = next((root / name for name in MANIFEST_NAMES if (root / name).is_file()), None)
    if manifest_path is None or manifest_path.is_symlink():
        return PackValidationResult(
            valid=False,
            issues=[
                PackValidationIssue(
                    code="manifest.missing", path="pack.yaml", message="Pack manifest is missing"
                )
            ],
        )

    try:
        raw_manifest = _load_yaml(manifest_path, MAX_MANIFEST_BYTES)
        manifest = PackManifest.model_validate(raw_manifest)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            issues.extend(_schema_issues(exc))
        else:
            issues.append(
                PackValidationIssue(
                    code="manifest.parse_failed",
                    path=manifest_path.name,
                    message="Manifest must be bounded UTF-8 YAML with unique keys and no aliases",
                )
            )
        return PackValidationResult(valid=False, issues=issues)

    if core_version is not None:
        try:
            current_core = Version(core_version)
        except ValueError:
            issues.append(
                PackValidationIssue(
                    code="core.version_invalid", message="Current Core version is invalid"
                )
            )
        else:
            if not manifest.supports_core(str(current_core)):
                issues.append(
                    PackValidationIssue(
                        code="core.incompatible",
                        message="Pack does not support the current Core version",
                    )
                )

    files: dict[str, Path] = {}
    paths: list[Path] = []
    try:
        for entry_number, path in enumerate(root.rglob("*"), start=1):
            if entry_number > MAX_PACKAGE_ENTRIES:
                issues.append(
                    PackValidationIssue(
                        code="package.too_many_entries",
                        message="Package contains too many file-system entries",
                    )
                )
                break
            paths.append(path)
    except OSError:
        issues.append(
            PackValidationIssue(
                code="package.read_failed", message="Package files could not be read"
            )
        )
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if len(relative) > 240 or len(path.relative_to(root).parts) > MAX_PATH_DEPTH:
            issues.append(
                PackValidationIssue(
                    code="content.path_too_deep",
                    path=relative[:240],
                    message="Package content path exceeds the path limit",
                )
            )
            continue
        if path.is_symlink():
            issues.append(
                PackValidationIssue(
                    code="content.symlink_forbidden",
                    path=relative,
                    message="Package symlinks are not allowed",
                )
            )
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            issues.append(
                PackValidationIssue(
                    code="content.not_regular_file",
                    path=relative,
                    message="Package entries must be regular files",
                )
            )
            continue
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt", ".yaml", ".yml"}:
            issues.append(
                PackValidationIssue(
                    code="content.type_forbidden",
                    path=relative,
                    message="Executable, binary and unsupported package files are forbidden",
                )
            )
            continue
        normalized_relative = relative.casefold()
        if normalized_relative in files:
            issues.append(
                PackValidationIssue(
                    code="content.path_collision",
                    path=relative,
                    message="Package paths must be unique across case-insensitive filesystems",
                )
            )
        files[normalized_relative] = path

    if len(files) > MAX_PACKAGE_FILES:
        issues.append(
            PackValidationIssue(
                code="package.too_many_files", message="Package contains too many content files"
            )
        )

    expected = {item.path.casefold(): item for item in manifest.content_checksums}
    actual = {key: path for key, path in files.items() if path != manifest_path}
    for key in sorted(set(expected) - set(actual)):
        issues.append(
            PackValidationIssue(
                code="content.missing",
                path=expected[key].path,
                message="Declared content file is missing",
            )
        )
    for key in sorted(set(actual) - set(expected)):
        issues.append(
            PackValidationIssue(
                code="content.unlisted",
                path=actual[key].relative_to(root).as_posix(),
                message="Every package file must be declared in content_checksums",
            )
        )

    for key in sorted(set(expected) & set(actual)):
        actual_path = actual[key].relative_to(root).as_posix()
        if expected[key].path != actual_path:
            issues.append(
                PackValidationIssue(
                    code="content.path_case_mismatch",
                    path=expected[key].path,
                    message="Declared content paths must match exact package path casing",
                )
            )

    digest = hashlib.sha256()
    canonical_manifest = json.dumps(
        manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest.update(len(canonical_manifest).to_bytes(4, "big"))
    digest.update(canonical_manifest)
    content_bytes = 0
    migration_operations: list[MigrationOperation] = []
    for key in sorted(set(expected) & set(actual)):
        path = actual[key]
        relative = expected[key].path
        try:
            size = path.stat().st_size
            content_bytes += size
            if size > MAX_CONTENT_BYTES:
                issues.append(
                    PackValidationIssue(
                        code="content.too_large",
                        path=relative,
                        message="Content file exceeds the size limit",
                    )
                )
                continue
            if content_bytes > MAX_PACKAGE_BYTES:
                issues.append(
                    PackValidationIssue(
                        code="package.too_large",
                        message="Total package content exceeds the size limit",
                    )
                )
                continue
            with path.open("rb") as source:
                data = source.read(MAX_CONTENT_BYTES + 1)
        except OSError:
            issues.append(
                PackValidationIssue(
                    code="content.read_failed",
                    path=relative,
                    message="Content file could not be read",
                )
            )
            continue
        if len(data) > MAX_CONTENT_BYTES:
            issues.append(
                PackValidationIssue(
                    code="content.too_large",
                    path=relative,
                    message="Content file exceeds the size limit",
                )
            )
            continue
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != expected[key].sha256:
            issues.append(
                PackValidationIssue(
                    code="content.digest_mismatch",
                    path=relative,
                    message="Content file checksum does not match the manifest",
                )
            )
        digest.update(len(relative.encode("utf-8")).to_bytes(4, "big"))
        digest.update(relative.encode("utf-8"))
        digest.update(bytes.fromhex(actual_sha256))
        if path.suffix.lower() in {".yaml", ".yml"}:
            try:
                document = _load_yaml(path, MAX_CONTENT_BYTES)
                if relative.casefold().startswith("migrations/"):
                    migration_file = PackMigrationFile.model_validate(document)
                    migration_operations.extend(migration_file.operations)
            except ValidationError:
                issues.append(
                    PackValidationIssue(
                        code="migration.invalid",
                        path=relative,
                        message="Migration must match the allowlisted typed review-only format",
                    )
                )
            except OSError, UnicodeDecodeError, yaml.YAMLError, ValueError:
                issues.append(
                    PackValidationIssue(
                        code="content.yaml_invalid",
                        path=relative,
                        message="YAML content must be bounded, valid, unique-key and alias-free",
                    )
                )
        elif relative.casefold().startswith("migrations/"):
            issues.append(
                PackValidationIssue(
                    code="migration.format_forbidden",
                    path=relative,
                    message="Migration descriptors must use the typed YAML format",
                )
            )
        elif path.suffix.lower() == ".json":
            try:
                _load_json(path, MAX_CONTENT_BYTES)
            except OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError:
                issues.append(
                    PackValidationIssue(
                        code="content.json_invalid",
                        path=relative,
                        message="JSON content must be bounded, valid and use unique object keys",
                    )
                )

    return PackValidationResult(
        valid=not issues,
        manifest=manifest,
        package_sha256=digest.hexdigest() if not issues else None,
        content_file_count=len(actual),
        content_bytes=content_bytes,
        migration_operations=migration_operations,
        issues=issues,
    )
