import hashlib
from pathlib import Path

import pytest
from operations.modules.domain_packs.infrastructure.registry import load_curated_registry


def _write_release(root: Path, pack_id: str, version: str = "1.0.0") -> None:
    release = root / pack_id / version
    release.mkdir(parents=True)
    content = b"Curated reference package\n"
    (release / "README.md").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    (release / "pack.yaml").write_text(
        "\n".join(
            [
                'schema_version: "1"',
                f"id: {pack_id}",
                f"name: {pack_id}",
                f"version: {version}",
                "pack_type: functional",
                'core_version_range: ">=1.0.0 <2.0.0"',
                "dependencies: []",
                "capabilities:",
                "  - forms",
                "content_checksums:",
                "  - path: README.md",
                f"    sha256: {digest}",
                "publisher: Platform Curators",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_curated_registry_loads_digest_pinned_release(tmp_path: Path) -> None:
    _write_release(tmp_path, "org.example.operations-basics")

    result = load_curated_registry(tmp_path)

    assert result.valid
    assert len(result.releases) == 1
    assert result.releases[0].manifest.id == "org.example.operations-basics"
    assert result.releases[0].registry_locator == "org.example.operations-basics/1.0.0"
    assert len(result.releases[0].content_sha256) == 64


def test_empty_curated_registry_is_valid(tmp_path: Path) -> None:
    result = load_curated_registry(tmp_path)

    assert result.valid
    assert result.releases == []


def test_registry_rejects_release_directory_that_disagrees_with_manifest(tmp_path: Path) -> None:
    _write_release(tmp_path, "org.example.operations-basics")
    manifest = tmp_path / "org.example.operations-basics" / "1.0.0" / "pack.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "id: org.example.operations-basics", "id: org.example.other-pack"
        ),
        encoding="utf-8",
    )

    result = load_curated_registry(tmp_path)

    assert not result.valid
    assert "registry.path_mismatch" in {issue.code for issue in result.issues}


def test_registry_refuses_symlink_root(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is not available on this platform")

    result = load_curated_registry(link)

    assert not result.valid
    assert result.issues[0].code == "registry.unavailable"
