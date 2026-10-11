"""Deterministic semantic-version dependency resolution for curated pack releases."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, StrictStr
from semantic_version import SimpleSpec, Version  # type: ignore[import-untyped]

from operations.contracts import Command
from operations.modules.domain_packs.application.manifest import (
    PackManifest,
    normalized_version_spec,
)
from operations.modules.domain_packs.application.migrations import MigrationOperation

MAX_RESOLVED_PACKS = 128
MAX_RESOLUTION_STEPS = 4096


class PackRelease(Command):
    manifest: PackManifest
    content_sha256: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")
    registry_locator: StrictStr = Field(min_length=1, max_length=240)
    migration_operations: list[MigrationOperation] = Field(default_factory=list)


class ResolutionIssue(Command):
    code: Literal[
        "pack.not_found",
        "dependency.not_found",
        "version.unsatisfied",
        "registry.version_collision",
        "dependency.cycle",
        "resolver.limit_exceeded",
        "core.incompatible",
    ]
    pack_id: str
    message: str


class DependencyResolution(Command):
    valid: bool
    selected: list[PackRelease] = Field(default_factory=list)
    issues: list[ResolutionIssue] = Field(default_factory=list)


@dataclass(frozen=True)
class _Constraint:
    version_range: str
    parent_id: str | None


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visited: set[str] = set()
    active: list[str] = []

    def visit(pack_id: str) -> list[str] | None:
        if pack_id in active:
            start = active.index(pack_id)
            return [*active[start:], pack_id]
        if pack_id in visited:
            return None
        active.append(pack_id)
        for dependency_id in sorted(graph.get(pack_id, set())):
            cycle = visit(dependency_id)
            if cycle is not None:
                return cycle
        active.pop()
        visited.add(pack_id)
        return None

    for pack_id in sorted(graph):
        cycle = visit(pack_id)
        if cycle is not None:
            return cycle
    return None


def _topological_order(selected: dict[str, PackRelease]) -> list[PackRelease]:
    ordered: list[PackRelease] = []
    visited: set[str] = set()

    def visit(pack_id: str) -> None:
        if pack_id in visited:
            return
        visited.add(pack_id)
        release = selected[pack_id]
        for dependency in sorted(release.manifest.dependencies, key=lambda item: item.id):
            visit(dependency.id)
        ordered.append(release)

    for pack_id in sorted(selected):
        visit(pack_id)
    return ordered


def resolve_dependencies(
    releases: Iterable[PackRelease],
    *,
    pack_id: str,
    version_range: str,
    core_version: str | None = None,
) -> DependencyResolution:
    """Select the highest compatible releases; return dependency-first order."""
    available: dict[str, list[PackRelease]] = {}
    identities: dict[tuple[str, str], PackRelease] = {}
    for release in releases:
        key = (release.manifest.id, release.manifest.version)
        previous_release = identities.get(key)
        if previous_release is not None and previous_release != release:
            return DependencyResolution(
                valid=False,
                issues=[
                    ResolutionIssue(
                        code="registry.version_collision",
                        pack_id=release.manifest.id,
                        message="One pack version is registered with different content digests",
                    )
                ],
            )
        identities[key] = release
        bucket = available.setdefault(release.manifest.id, [])
        if all(item.manifest.version != release.manifest.version for item in bucket):
            bucket.append(release)
    for bucket in available.values():
        bucket.sort(key=lambda item: Version(item.manifest.version), reverse=True)

    constraints: dict[str, list[_Constraint]] = {
        pack_id: [_Constraint(version_range=version_range, parent_id=None)]
    }
    step_count = 0
    failures: list[ResolutionIssue] = []

    def search(
        selected: dict[str, PackRelease],
        required: dict[str, list[_Constraint]],
        graph: dict[str, set[str]],
    ) -> tuple[dict[str, PackRelease], dict[str, set[str]]] | None:
        nonlocal step_count
        step_count += 1
        if step_count > MAX_RESOLUTION_STEPS or len(required) > MAX_RESOLVED_PACKS:
            failures.append(
                ResolutionIssue(
                    code="resolver.limit_exceeded",
                    pack_id=pack_id,
                    message="Dependency resolution exceeded its bounded search limits",
                )
            )
            return None

        for selected_id, selected_release in selected.items():
            if not _satisfies(selected_release, required.get(selected_id, [])):
                parent = next(
                    (item.parent_id for item in required[selected_id] if item.parent_id),
                    None,
                )
                failures.append(
                    ResolutionIssue(
                        code="version.unsatisfied",
                        pack_id=selected_id,
                        message=(
                            f"Selected {selected_id}@{selected_release.manifest.version} "
                            "does not satisfy a dependency constraint from "
                            f"{parent or 'the request'}"
                        ),
                    )
                )
                return None

        unresolved = sorted(set(required) - set(selected))
        if not unresolved:
            cycle = _find_cycle(graph)
            if cycle is not None:
                failures.append(
                    ResolutionIssue(
                        code="dependency.cycle",
                        pack_id=cycle[0],
                        message="Pack dependency cycle: " + " -> ".join(cycle),
                    )
                )
                return None
            return selected, graph

        next_id = unresolved[0]
        candidates = available.get(next_id, [])
        if not candidates:
            parent = next((item.parent_id for item in required[next_id] if item.parent_id), None)
            failures.append(
                ResolutionIssue(
                    code="pack.not_found" if parent is None else "dependency.not_found",
                    pack_id=next_id,
                    message=(
                        f"No curated registry release exists for {next_id}"
                        if parent is None
                        else f"{parent} depends on unavailable pack {next_id}"
                    ),
                )
            )
            return None

        version_compatible = [
            candidate for candidate in candidates if _satisfies(candidate, required[next_id])
        ]
        compatible = [
            candidate
            for candidate in version_compatible
            if core_version is None or candidate.manifest.supports_core(core_version)
        ]
        if not compatible:
            if version_compatible:
                failures.append(
                    ResolutionIssue(
                        code="core.incompatible",
                        pack_id=next_id,
                        message=f"No compatible release of {next_id} supports Core {core_version}",
                    )
                )
                return None
            parent = next((item.parent_id for item in required[next_id] if item.parent_id), None)
            failures.append(
                ResolutionIssue(
                    code="version.unsatisfied",
                    pack_id=next_id,
                    message=(
                        f"No curated release of {next_id} satisfies all requested version ranges"
                        + (f" required by {parent}" if parent else "")
                    ),
                )
            )
            return None

        for candidate in compatible:
            branch_selected = dict(selected)
            branch_selected[next_id] = candidate
            branch_required = {key: list(value) for key, value in required.items()}
            branch_graph = {key: set(value) for key, value in graph.items()}
            branch_graph.setdefault(next_id, set())
            for dependency in candidate.manifest.dependencies:
                branch_required.setdefault(dependency.id, []).append(
                    _Constraint(version_range=dependency.version_range, parent_id=next_id)
                )
                branch_graph[next_id].add(dependency.id)
            resolved = search(branch_selected, branch_required, branch_graph)
            if resolved is not None:
                return resolved
        return None

    try:
        SimpleSpec(normalized_version_spec(version_range))
    except ValueError:
        return DependencyResolution(
            valid=False,
            issues=[
                ResolutionIssue(
                    code="version.unsatisfied",
                    pack_id=pack_id,
                    message="Requested version range is invalid",
                )
            ],
        )

    result = search({}, constraints, {})
    if result is None:
        issues = failures or [
            ResolutionIssue(
                code="version.unsatisfied",
                pack_id=pack_id,
                message="No compatible dependency solution exists",
            )
        ]
        return DependencyResolution(valid=False, issues=issues[:1])
    selected, _ = result
    return DependencyResolution(valid=True, selected=_topological_order(selected))


def _satisfies(release: PackRelease, constraints: list[_Constraint]) -> bool:
    version = Version(release.manifest.version)
    return all(
        version in SimpleSpec(normalized_version_spec(constraint.version_range))
        for constraint in constraints
    )
