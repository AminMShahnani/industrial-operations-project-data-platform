import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from operations.modules.domain_packs.application.manifest import PackManifest
from operations.modules.domain_packs.application.validation import validate_pack_directory


def _write_pack(root: Path, *, core_range: str = ">=1.0.0 <2.0.0") -> None:
    root.mkdir(parents=True, exist_ok=True)
    artifact_path = root / "forms" / "daily.yaml"
    artifact_path.parent.mkdir()
    artifact = b"title: Generic operational form\nfields: []\n"
    artifact_path.write_bytes(artifact)
    digest = hashlib.sha256(artifact).hexdigest()
    (root / "pack.yaml").write_text(
        "\n".join(
            [
                'schema_version: "1"',
                "id: org.example.operations-basics",
                "name: Operations Basics",
                "version: 1.2.3",
                "pack_type: functional",
                f'core_version_range: "{core_range}"',
                "dependencies: []",
                "capabilities:",
                "  - forms",
                "content_checksums:",
                "  - path: forms/daily.yaml",
                f"    sha256: {digest}",
                "publisher: Platform Curators",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_validates_typed_pack_and_core_compatibility(tmp_path: Path) -> None:
    _write_pack(tmp_path / "pack")

    result = validate_pack_directory(tmp_path / "pack", core_version="1.4.0")

    assert result.valid
    assert result.manifest is not None
    assert result.manifest.id == "org.example.operations-basics"
    assert result.manifest.supports_core("1.9.0")
    assert result.package_sha256 is not None
    assert result.content_file_count == 1


def test_rejects_core_incompatibility(tmp_path: Path) -> None:
    _write_pack(tmp_path / "pack")

    result = validate_pack_directory(tmp_path / "pack", core_version="2.0.0")

    assert not result.valid
    assert "core.incompatible" in {issue.code for issue in result.issues}


def test_rejects_content_digest_mismatch(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_pack(pack)
    (pack / "forms" / "daily.yaml").write_text("title: changed\n", encoding="utf-8")

    result = validate_pack_directory(pack)

    assert not result.valid
    assert "content.digest_mismatch" in {issue.code for issue in result.issues}


def test_rejects_unlisted_executable_file(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_pack(pack)
    (pack / "run.py").write_text("print('must not execute')\n", encoding="utf-8")

    result = validate_pack_directory(pack)

    assert not result.valid
    assert "content.type_forbidden" in {issue.code for issue in result.issues}


@pytest.mark.parametrize(
    "manifest_change",
    [
        lambda text: text.replace('schema_version: "1"', 'schema_version: "9"'),
        lambda text: text.replace("version: 1.2.3", "version: 1.2"),
        lambda text: text.replace("  - forms", "  - arbitrary-execution"),
        lambda text: text.replace(
            "dependencies: []",
            "dependencies:\n  - id: org.example.operations-basics\n    version_range: '>=1.0.0'",
        ),
    ],
)
def test_rejects_invalid_manifest_contract(
    tmp_path: Path, manifest_change: Callable[[str], str]
) -> None:
    pack = tmp_path / "pack"
    _write_pack(pack)
    manifest = pack / "pack.yaml"
    manifest.write_text(manifest_change(manifest.read_text(encoding="utf-8")), encoding="utf-8")

    result = validate_pack_directory(pack)

    assert not result.valid
    assert any(issue.code == "manifest.invalid" for issue in result.issues)


def test_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_pack(pack)
    manifest = pack / "pack.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "name: Operations Basics", "name: First\nname: Second"
        ),
        encoding="utf-8",
    )

    result = validate_pack_directory(pack)

    assert not result.valid
    assert "manifest.parse_failed" in {issue.code for issue in result.issues}


def test_rejects_yaml_aliases_and_python_object_tags(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_pack(pack)
    manifest = pack / "pack.yaml"
    text = manifest.read_text(encoding="utf-8").replace(
        "dependencies: []", "defaults: &defaults []\ndependencies: *defaults"
    )
    manifest.write_text(text, encoding="utf-8")
    result = validate_pack_directory(pack)
    assert "manifest.parse_failed" in {issue.code for issue in result.issues}

    manifest.write_text("!!python/object/apply:os.system ['echo unsafe']\n", encoding="utf-8")
    tagged_result = validate_pack_directory(pack)
    assert "manifest.parse_failed" in {issue.code for issue in tagged_result.issues}


def test_rejects_unlisted_and_invalid_json_files(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_pack(pack)
    (pack / "extra.json").write_text('{"key":1,"key":2}', encoding="utf-8")

    result = validate_pack_directory(pack)

    assert not result.valid
    assert "content.unlisted" in {issue.code for issue in result.issues}


def test_manifest_json_schema_is_explicit_and_versioned() -> None:
    schema = PackManifest.model_json_schema()

    assert "schema_version" in schema["properties"]
    assert schema["additionalProperties"] is False


def test_checked_in_sdk_schema_has_no_drift() -> None:
    root = Path(__file__).parents[2]
    checked_in = json.loads(
        (root / "contracts" / "domain-pack-manifest.schema.json").read_text(encoding="utf-8")
    )

    assert checked_in == PackManifest.model_json_schema()


def test_rejects_duplicate_keys_in_declared_json_content(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_pack(pack)
    json_content = b'{"mode":"safe","mode":"unsafe"}'
    (pack / "metadata.json").write_bytes(json_content)
    manifest_path = pack / "pack.yaml"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_text = manifest_text.replace(
        "publisher: Platform Curators",
        "  - path: metadata.json\n"
        f"    sha256: {hashlib.sha256(json_content).hexdigest()}\n"
        "publisher: Platform Curators",
    )
    manifest_path.write_text(manifest_text, encoding="utf-8")

    result = validate_pack_directory(pack)

    assert not result.valid
    assert "content.json_invalid" in {issue.code for issue in result.issues}


def _write_migration_pack(root: Path, migration: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    readme.write_text("Pack migration test\n", encoding="utf-8")
    migration_path = root / "migrations" / "1.1.0.yaml"
    migration_path.parent.mkdir()
    migration_path.write_text(migration, encoding="utf-8")
    manifest = {
        "schema_version": "1",
        "id": "org.example.operations-basics",
        "name": "Operations Basics",
        "version": "1.1.0",
        "pack_type": "functional",
        "core_version_range": ">=1.0.0 <2.0.0",
        "dependencies": [],
        "capabilities": ["forms"],
        "content_checksums": [
            {"path": "README.md", "sha256": hashlib.sha256(readme.read_bytes()).hexdigest()},
            {
                "path": "migrations/1.1.0.yaml",
                "sha256": hashlib.sha256(migration_path.read_bytes()).hexdigest(),
            },
        ],
        "publisher": "Platform Curators",
    }
    (root / "pack.yaml").write_text(json.dumps(manifest), encoding="utf-8")


def test_validates_allowlisted_migration_and_returns_review_operations(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_migration_pack(
        pack,
        """schema_version: 1
operations:
  - operation: add_optional_field
    artifact_kind: form
    artifact_id: daily-inspection
    field_id: supervisor_note
    field_type: text
    label: Supervisor note
  - operation: deprecate_artifact
    artifact_kind: form
    artifact_id: legacy-inspection
    reason: Replaced by daily-inspection
""",
    )

    result = validate_pack_directory(pack)

    assert result.valid
    assert [item.operation for item in result.migration_operations] == [
        "add_optional_field",
        "deprecate_artifact",
    ]


def test_rejects_arbitrary_migration_operation_and_payload(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_migration_pack(
        pack,
        """schema_version: 1
operations:
  - operation: execute_sql
    sql: DROP TABLE submissions
""",
    )

    result = validate_pack_directory(pack)

    assert not result.valid
    assert "migration.invalid" in {issue.code for issue in result.issues}
