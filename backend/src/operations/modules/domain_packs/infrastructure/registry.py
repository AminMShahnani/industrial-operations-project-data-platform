"""Read-only adapter for the platform-curated, source-controlled pack registry."""

from pathlib import Path

from semantic_version import Version  # type: ignore[import-untyped]

from operations.modules.domain_packs.application.dependency_resolution import PackRelease
from operations.modules.domain_packs.application.registry import RegistryIssue, RegistrySnapshot
from operations.modules.domain_packs.application.validation import validate_pack_directory

MAX_REGISTRY_PACKS = 500
MAX_REGISTRY_RELEASES = 2000


class CuratedPackRegistry:
    def __init__(self, registry_root: str | Path) -> None:
        self.registry_root = Path(registry_root)

    def snapshot(self) -> RegistrySnapshot:
        return load_curated_registry(self.registry_root)


def load_curated_registry(
    registry_root: Path,
) -> RegistrySnapshot:
    """Validate registry packages from disk; never downloads or executes package content."""
    if registry_root.is_symlink() or not registry_root.is_dir():
        return RegistrySnapshot(
            valid=False,
            issues=[
                RegistryIssue(
                    code="registry.unavailable",
                    message="Curated registry directory is unavailable",
                )
            ],
        )
    root = registry_root.resolve()
    issues: list[RegistryIssue] = []
    releases: list[PackRelease] = []
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        return RegistrySnapshot(
            valid=False,
            issues=[
                RegistryIssue(
                    code="registry.read_failed", message="Curated registry could not be read"
                )
            ],
        )

    pack_entries = [entry for entry in entries if entry.name != "README.md"]
    if len(pack_entries) > MAX_REGISTRY_PACKS:
        return RegistrySnapshot(
            valid=False,
            issues=[
                RegistryIssue(
                    code="registry.too_many_packs", message="Registry contains too many pack ids"
                )
            ],
        )

    for pack_entry in pack_entries:
        if pack_entry.is_symlink() or not pack_entry.is_dir():
            issues.append(
                RegistryIssue(
                    code="registry.entry_invalid",
                    locator=pack_entry.name,
                    message="Registry entries must be pack-id directories",
                )
            )
            continue
        try:
            versions = sorted(pack_entry.iterdir(), key=lambda item: item.name)
        except OSError:
            issues.append(
                RegistryIssue(
                    code="registry.read_failed",
                    locator=pack_entry.name,
                    message="Pack releases could not be read",
                )
            )
            continue
        for version_entry in versions:
            locator = f"{pack_entry.name}/{version_entry.name}"
            if len(releases) >= MAX_REGISTRY_RELEASES:
                issues.append(
                    RegistryIssue(
                        code="registry.too_many_releases",
                        message="Registry contains too many pack releases",
                    )
                )
                break
            if version_entry.is_symlink() or not version_entry.is_dir():
                issues.append(
                    RegistryIssue(
                        code="registry.entry_invalid",
                        locator=locator,
                        message="Pack versions must be release directories",
                    )
                )
                continue
            validation = validate_pack_directory(version_entry)
            if (
                not validation.valid
                or validation.manifest is None
                or validation.package_sha256 is None
            ):
                issues.extend(
                    RegistryIssue(
                        code=f"package.{issue.code}",
                        locator=locator,
                        message=issue.message,
                    )
                    for issue in validation.issues
                )
                continue
            manifest = validation.manifest
            if manifest.id != pack_entry.name or manifest.version != version_entry.name:
                issues.append(
                    RegistryIssue(
                        code="registry.path_mismatch",
                        locator=locator,
                        message="Registry path must match manifest pack id and version",
                    )
                )
                continue
            try:
                Version(version_entry.name)
            except ValueError:
                issues.append(
                    RegistryIssue(
                        code="registry.version_invalid",
                        locator=locator,
                        message="Registry release directory must use a semantic version",
                    )
                )
                continue
            releases.append(
                PackRelease(
                    manifest=manifest,
                    content_sha256=validation.package_sha256,
                    registry_locator=locator,
                    migration_operations=validation.migration_operations,
                )
            )

    return RegistrySnapshot(valid=not issues, releases=releases, issues=issues)
