from operations.modules.domain_packs.application.dependency_resolution import (
    PackRelease,
    resolve_dependencies,
)
from operations.modules.domain_packs.application.manifest import (
    PackCapability,
    PackContentChecksum,
    PackDependency,
    PackManifest,
    PackType,
)

_DIGEST = "a" * 64


def _release(
    pack_id: str,
    version: str,
    dependencies: list[PackDependency] | None = None,
    *,
    digest: str = _DIGEST,
) -> PackRelease:
    manifest = PackManifest(
        schema_version="1",
        id=pack_id,
        name=pack_id,
        version=version,
        pack_type=PackType.FUNCTIONAL,
        core_version_range=">=1.0.0 <2.0.0",
        dependencies=dependencies or [],
        capabilities=[PackCapability.FORMS],
        content_checksums=[PackContentChecksum(path="README.md", sha256=_DIGEST)],
        publisher="Curated Test Publisher",
    )
    return PackRelease(
        manifest=manifest,
        content_sha256=digest,
        registry_locator=f"domain-packs/registry/{pack_id}/{version}",
    )


def _dependency(pack_id: str, version_range: str) -> PackDependency:
    return PackDependency(id=pack_id, version_range=version_range)


def test_resolves_highest_compatible_release_dependency_first() -> None:
    releases = [
        _release(
            "org.example.app",
            "1.0.0",
            [_dependency("org.example.common", ">=1.0.0 <2.0.0")],
        ),
        _release("org.example.common", "1.1.0"),
        _release("org.example.common", "1.8.0"),
        _release("org.example.common", "2.0.0"),
    ]

    result = resolve_dependencies(
        releases, pack_id="org.example.app", version_range=">=1.0.0 <2.0.0"
    )

    assert result.valid
    assert [(item.manifest.id, item.manifest.version) for item in result.selected] == [
        ("org.example.common", "1.8.0"),
        ("org.example.app", "1.0.0"),
    ]


def test_missing_transitive_dependency_is_reported() -> None:
    release = _release(
        "org.example.app",
        "1.0.0",
        [_dependency("org.example.missing", ">=1.0.0")],
    )

    result = resolve_dependencies([release], pack_id="org.example.app", version_range=">=1.0.0")

    assert not result.valid
    assert result.issues[0].code == "dependency.not_found"
    assert result.issues[0].pack_id == "org.example.missing"


def test_conflicting_transitive_constraints_have_no_solution() -> None:
    releases = [
        _release(
            "org.example.app",
            "1.0.0",
            [
                _dependency("org.example.first", ">=1.0.0"),
                _dependency("org.example.second", ">=1.0.0"),
            ],
        ),
        _release(
            "org.example.first",
            "1.0.0",
            [_dependency("org.example.common", ">=1.0.0 <2.0.0")],
        ),
        _release(
            "org.example.second",
            "1.0.0",
            [_dependency("org.example.common", ">=2.0.0 <3.0.0")],
        ),
        _release("org.example.common", "1.9.0"),
        _release("org.example.common", "2.1.0"),
    ]

    result = resolve_dependencies(releases, pack_id="org.example.app", version_range=">=1.0.0")

    assert not result.valid
    assert result.issues[0].code == "version.unsatisfied"


def test_dependency_cycle_is_rejected() -> None:
    releases = [
        _release(
            "org.example.first",
            "1.0.0",
            [_dependency("org.example.second", ">=1.0.0")],
        ),
        _release(
            "org.example.second",
            "1.0.0",
            [_dependency("org.example.first", ">=1.0.0")],
        ),
    ]

    result = resolve_dependencies(releases, pack_id="org.example.first", version_range=">=1.0.0")

    assert not result.valid
    assert result.issues[0].code == "dependency.cycle"


def test_same_pack_version_with_different_registry_content_is_rejected() -> None:
    releases = [
        _release("org.example.app", "1.0.0", digest="b" * 64),
        _release("org.example.app", "1.0.0", digest="c" * 64),
    ]

    result = resolve_dependencies(releases, pack_id="org.example.app", version_range=">=1.0.0")

    assert not result.valid
    assert result.issues[0].code == "registry.version_collision"


def test_current_core_compatibility_is_enforced_during_resolution() -> None:
    release = _release("org.example.app", "1.0.0")
    release = release.model_copy(
        update={
            "manifest": release.manifest.model_copy(update={"core_version_range": ">=2.0.0 <3.0.0"})
        }
    )

    result = resolve_dependencies(
        [release],
        pack_id="org.example.app",
        version_range=">=1.0.0",
        core_version="1.4.0",
    )

    assert not result.valid
    assert result.issues[0].code == "core.incompatible"
