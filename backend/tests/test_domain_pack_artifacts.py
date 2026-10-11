import hashlib
import json
from pathlib import Path

import pytest
from operations.modules.domain_packs.application.artifacts import (
    PackArtifactKind,
    artifact_json_schema,
    validate_artifact,
)
from operations.modules.domain_packs.application.validation import validate_pack_directory


def _form(artifact_id: str = "daily-report") -> dict[str, object]:
    return {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "artifact_version": 1,
        "kind": "form",
        "name": "Daily report",
        "description": "",
        "definition": {
            "sections": [
                {
                    "key": "general",
                    "label": "General",
                    "components": [
                        {
                            "key": "well_name",
                            "kind": "text",
                            "label": "Well name",
                            "required": True,
                        }
                    ],
                }
            ]
        },
    }


def _write_package(root: Path, artifacts: list[dict[str, object]]) -> None:
    checksums: list[dict[str, str]] = []
    for document in artifacts:
        kind = str(document["kind"])
        artifact_id = str(document["artifact_id"])
        path = root / "artifacts" / kind / f"{artifact_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(document, sort_keys=True).encode()
        path.write_bytes(content)
        checksums.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {
        "schema_version": "1",
        "id": "org.example.oil-gas",
        "name": "Oil & Gas Operations",
        "version": "1.0.0",
        "pack_type": "functional",
        "core_version_range": ">=0.1.0 <1.0.0",
        "dependencies": [],
        "capabilities": ["forms"],
        "content_checksums": checksums,
        "publisher": "Platform Curators",
    }
    (root / "pack.yaml").write_text(json.dumps(manifest), encoding="utf-8")


def test_typed_form_artifact_and_schema() -> None:
    artifact = validate_artifact(_form())

    assert artifact.envelope.kind == PackArtifactKind.FORM
    schema = artifact_json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert len(schema["oneOf"]) == 6  # type: ignore[arg-type]


def test_automation_template_is_bounded_and_inert() -> None:
    document = {
        "schema_version": 1,
        "artifact_id": "overdue-escalation",
        "artifact_version": 1,
        "kind": "automation_template",
        "name": "Overdue escalation",
        "description": "",
        "definition": {
            "trigger": "task.overdue",
            "action": "notify_manager",
            "threshold_hours": 24,
        },
    }

    result = validate_artifact(document)

    assert result.envelope.kind == PackArtifactKind.AUTOMATION_TEMPLATE


def test_rejects_reference_outside_typed_slot() -> None:
    document = _form()
    document["definition"] = {
        "title": {
            "$artifact_ref": {
                "pack_id": "org.example.oil-gas",
                "kind": "form",
                "artifact_id": "daily-report",
                "version": 1,
            }
        }
    }

    with pytest.raises(ValueError, match="artifact_reference_in_unsupported_field"):
        validate_artifact(document)


def test_package_validator_requires_exact_existing_reference_and_no_cycles(tmp_path: Path) -> None:
    first = _form("first")
    second = _form("second")
    first["definition"] = {
        "sections": [
            {
                "key": "general",
                "label": "General",
                "components": [
                    {
                        "key": "well_name",
                        "kind": "master_data",
                        "label": "Well",
                        "source": {
                            "type_id": {
                                "$artifact_ref": {
                                    "pack_id": "org.example.oil-gas",
                                    "pack_version": "1.0.0",
                                    "kind": "master_data_type",
                                    "artifact_id": "well",
                                    "version": 2,
                                }
                            }
                        },
                    }
                ],
            }
        ]
    }
    _write_package(tmp_path / "pack", [first, second])

    result = validate_pack_directory(tmp_path / "pack")

    assert not result.valid
    assert "artifact.reference_missing" in {issue.code for issue in result.issues}


def test_package_validator_rejects_reference_cycle(tmp_path: Path) -> None:
    def data_type(artifact_id: str, reference: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_id": artifact_id,
            "artifact_version": 1,
            "kind": "master_data_type",
            "name": artifact_id,
            "description": "",
            "definition": {
                "code": artifact_id,
                "name": artifact_id,
                "registry": "custom",
                "definition": {
                    "fields": [
                        {
                            "key": "related",
                            "kind": "reference",
                            "reference_type_id": {
                                "$artifact_ref": {
                                    "pack_id": "org.example.oil-gas",
                                    "pack_version": "1.0.0",
                                    "kind": "master_data_type",
                                    "artifact_id": reference,
                                    "version": 1,
                                }
                            },
                        }
                    ]
                },
            },
        }

    _write_package(
        tmp_path / "pack", [data_type("type-a", "type-b"), data_type("type-b", "type-a")]
    )

    result = validate_pack_directory(tmp_path / "pack")

    assert not result.valid
    assert "artifact.reference_cycle" in {issue.code for issue in result.issues}


def test_rejects_duplicate_stable_artifact_ids(tmp_path: Path) -> None:
    first = _form("same-id")
    second = {
        "schema_version": 1,
        "artifact_id": "same-id",
        "artifact_version": 1,
        "kind": "mapping_profile",
        "name": "Mapping",
        "description": "",
        "definition": {
            "source_kind": "internal.well",
            "target_kind": "internal.site",
            "fields": [{"source_key": "well_name", "target_key": "name"}],
        },
    }
    _write_package(tmp_path / "pack", [first, second])

    result = validate_pack_directory(tmp_path / "pack")

    assert not result.valid
    assert "artifact.duplicate_id" in {issue.code for issue in result.issues}


def test_rejects_artifact_path_kind_mismatch(tmp_path: Path) -> None:
    artifact = _form()
    _write_package(tmp_path / "pack", [artifact])
    path = tmp_path / "pack" / "artifacts" / "form" / "daily-report.json"
    content = path.read_bytes()
    moved = tmp_path / "pack" / "artifacts" / "workflow" / "daily-report.json"
    moved.parent.mkdir(parents=True)
    moved.write_bytes(content)
    path.unlink()
    manifest_path = tmp_path / "pack" / "pack.yaml"
    manifest = json.loads(manifest_path.read_text())
    manifest["content_checksums"] = [
        {
            "path": moved.relative_to(tmp_path / "pack").as_posix(),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    ]
    manifest_path.write_text(json.dumps(manifest))

    result = validate_pack_directory(tmp_path / "pack")

    assert not result.valid
    assert "artifact.path_mismatch" in {issue.code for issue in result.issues}


def test_curated_oil_gas_release_contains_starter_templates() -> None:
    root = Path(__file__).parents[2] / "domain-packs" / "registry" / "org.example.oil-gas" / "1.0.0"

    result = validate_pack_directory(root, core_version="0.1.0")

    assert result.valid
    assert result.manifest is not None
    by_kind: dict[str, int] = {}
    for artifact in result.artifacts:
        by_kind[artifact.kind.value] = by_kind.get(artifact.kind.value, 0) + 1
    assert by_kind == {
        "form": 13,
        "master_data_type": 16,
        "workflow": 4,
        "automation_template": 3,
        "kpi": 7,
        "mapping_profile": 3,
    }
    assert not any(path.name in {".env", "credentials.json"} for path in root.rglob("*"))
