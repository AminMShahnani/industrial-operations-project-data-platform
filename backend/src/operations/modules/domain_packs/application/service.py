"""Authorized, dry-run-bound organization Domain Pack lifecycle service."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid7

from semantic_version import Version  # type: ignore[import-untyped]

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent
from operations.modules.domain_packs.application.contracts import (
    AuditAppender,
    AuthorizationService,
    InstallationPage,
    InstallationState,
    LifecycleApplyRequest,
    LifecycleOperation,
    LifecyclePlan,
    LifecyclePlanIssue,
    LifecyclePlanRequest,
    LifecyclePlanStep,
    OrganizationLifecycle,
    PackInstallation,
    PackInstallationStore,
    PackRegistryProvider,
    PlanStepAction,
)
from operations.modules.domain_packs.application.dependency_resolution import (
    PackRelease,
    ResolutionIssue,
    resolve_dependencies,
)
from operations.modules.domain_packs.application.registry import RegistrySnapshot
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.identity.application.contracts import RequestContext, User


class DomainPackService:
    def __init__(
        self,
        registry: PackRegistryProvider,
        installations: PackInstallationStore,
        authorization: AuthorizationService,
        organizations: OrganizationLifecycle,
        audit: AuditAppender,
        core_version: str,
    ) -> None:
        self.registry = registry
        self.installations = installations
        self.authorization = authorization
        self.organizations = organizations
        self.audit = audit
        self.core_version = core_version

    def catalog(self, context: RequestContext, organization_id: UUID) -> RegistrySnapshot:
        self._authorize(context, organization_id, "organization.read")
        self.organizations.active(organization_id)
        snapshot = self.registry.snapshot()
        if not snapshot.valid:
            raise ServiceError(503, "domain_pack_registry_unavailable")
        return snapshot

    def installed(self, context: RequestContext, organization_id: UUID) -> InstallationPage:
        self._authorize(context, organization_id, "organization.read")
        self.organizations.active(organization_id)
        return InstallationPage(items=self.installations.installations(organization_id))

    def plan(
        self, context: RequestContext, organization_id: UUID, request: LifecyclePlanRequest
    ) -> LifecyclePlan:
        self._authorize(context, organization_id, "domain_pack.install")
        self.organizations.active(organization_id)
        self.organizations.lock(organization_id)
        snapshot = self.registry.snapshot()
        issues: list[LifecyclePlanIssue] = [
            LifecyclePlanIssue(
                code="registry.invalid", pack_id=request.pack_id, message=issue.message
            )
            for issue in snapshot.issues
        ]
        if not snapshot.valid:
            return self._plan_result(organization_id, request, [], [], issues)

        current = {item.pack_id: item for item in self.installations.installations(organization_id)}
        releases: list[PackRelease] = []
        steps: list[LifecyclePlanStep] = []

        if request.operation in {LifecycleOperation.INSTALL, LifecycleOperation.UPGRADE}:
            if request.version_range is None:
                issues.append(
                    LifecyclePlanIssue(
                        code="version_range.required",
                        pack_id=request.pack_id,
                        message="Install and upgrade plans require a version range",
                    )
                )
            else:
                resolved = resolve_dependencies(
                    snapshot.releases,
                    pack_id=request.pack_id,
                    version_range=request.version_range,
                    core_version=self.core_version,
                )
                issues.extend(self._resolution_issues(resolved.issues))
                releases = resolved.selected if resolved.valid else []
                if resolved.valid:
                    steps.extend(self._release_steps(request, releases, current, issues))
        else:
            self._state_operation(
                request, current, snapshot.releases, steps, issues, organization_id
            )

        return self._plan_result(organization_id, request, releases, steps, issues, current)

    def apply(
        self, context: RequestContext, organization_id: UUID, request: LifecycleApplyRequest
    ) -> InstallationPage:
        actor = self._authorize(context, organization_id, "domain_pack.install")
        self.organizations.active(organization_id)
        self.organizations.lock(organization_id)
        plan_request = LifecyclePlanRequest(
            operation=request.operation,
            pack_id=request.pack_id,
            version_range=request.version_range,
        )
        plan = self.plan(context, organization_id, plan_request)
        if not plan.valid or plan.plan_sha256 is None:
            raise ServiceError(422, "domain_pack_plan_invalid")
        if plan.plan_sha256 != request.expected_plan_sha256:
            raise ServiceError(409, "domain_pack_plan_stale")
        if (
            any(step.requires_breaking_review for step in plan.steps)
            and not request.confirm_breaking_change
        ):
            raise ServiceError(422, "domain_pack_breaking_change_confirmation_required")
        if request.reason != request.reason.strip():
            raise ServiceError(422, "invalid_reason")

        selected = {release.manifest.id: release for release in plan.selected_releases}
        for step in plan.steps:
            if step.action in {PlanStepAction.INSTALL, PlanStepAction.UPGRADE}:
                release = selected.get(step.pack_id)
                current_release = self.installations.registry_release(
                    step.pack_id, step.to_version or ""
                )
                if (
                    release is None
                    or current_release is None
                    or current_release.content_sha256 != release.content_sha256
                    or current_release.content_sha256 != step.content_sha256
                ):
                    raise ServiceError(409, "domain_pack_plan_stale")
        if all(step.action == PlanStepAction.NOOP for step in plan.steps):
            return InstallationPage(items=self.installations.installations(organization_id))
        now = datetime.now(UTC)
        for step in plan.steps:
            if step.action == PlanStepAction.NOOP:
                continue
            existing = self.installations.get(organization_id, step.pack_id)
            release = selected.get(step.pack_id)
            if step.action == PlanStepAction.INSTALL:
                if release is None:
                    raise ServiceError(409, "domain_pack_plan_stale")
                installation = PackInstallation(
                    id=existing.id if existing else uuid7(),
                    organization_id=organization_id,
                    pack_id=step.pack_id,
                    version=release.manifest.version,
                    content_sha256=release.content_sha256,
                    state=InstallationState.INSTALLED,
                    row_version=(existing.row_version + 1) if existing else 1,
                    created_at=existing.created_at if existing else now,
                    updated_at=now,
                    installed_by=existing.installed_by if existing else actor.id,
                )
                if existing is None:
                    self.installations.create(installation)
                else:
                    if (
                        existing.row_version != step.expected_row_version
                        or not self.installations.update(installation, existing.row_version)
                    ):
                        raise ServiceError(409, "domain_pack_plan_stale")
                self.installations.add_provenance(
                    organization_id,
                    installation.id,
                    release.manifest.id,
                    release.manifest.version,
                    release.content_sha256,
                    release.manifest.content_checksums,
                )
            else:
                if existing is None or existing.row_version != step.expected_row_version:
                    raise ServiceError(409, "domain_pack_plan_stale")
                state = self._next_state(step.action, existing.state)
                installation = existing.model_copy(
                    update={
                        "state": state,
                        "updated_at": now,
                        "row_version": existing.row_version + 1,
                    }
                )
                if step.action == PlanStepAction.UPGRADE:
                    if release is None:
                        raise ServiceError(409, "domain_pack_plan_stale")
                    installation = installation.model_copy(
                        update={
                            "version": release.manifest.version,
                            "content_sha256": release.content_sha256,
                        }
                    )
                    self.installations.add_provenance(
                        organization_id,
                        installation.id,
                        release.manifest.id,
                        release.manifest.version,
                        release.content_sha256,
                        release.manifest.content_checksums,
                    )
                if not self.installations.update(installation, existing.row_version):
                    raise ServiceError(409, "domain_pack_plan_stale")

            self.audit.append(
                AuditEvent(
                    id=uuid7(),
                    type=f"domain_pack.{step.action.value}",
                    occurred_at=now,
                    organization_id=organization_id,
                    actor_id=actor.id,
                    correlation_id=context.correlation_id,
                    request_id=context.request_id,
                    aggregate_type="domain_pack_installation",
                    aggregate_id=installation.id,
                    payload=AuditDetails(
                        target_id=installation.id,
                        reason=request.reason,
                        version=installation.row_version,
                        outcome=installation.state.value,
                        pack_id=installation.pack_id,
                        pack_version=installation.version,
                        package_sha256=installation.content_sha256,
                    ),
                )
            )
        return InstallationPage(items=self.installations.installations(organization_id))

    def _authorize(self, context: RequestContext, organization_id: UUID, permission: str) -> User:
        scope = Scope(organization_id, ScopeType.ORGANIZATION, organization_id)
        return self.authorization.require(context, permission, scope)

    def _release_steps(
        self,
        request: LifecyclePlanRequest,
        releases: list[PackRelease],
        current: dict[str, PackInstallation],
        issues: list[LifecyclePlanIssue],
    ) -> list[LifecyclePlanStep]:
        result: list[LifecyclePlanStep] = []
        for release in releases:
            existing = current.get(release.manifest.id)
            if existing is None or existing.state == InstallationState.UNINSTALLED:
                action = PlanStepAction.INSTALL
                if (
                    release.manifest.id == request.pack_id
                    and request.operation == LifecycleOperation.UPGRADE
                ):
                    issues.append(
                        LifecyclePlanIssue(
                            code="installation.missing",
                            pack_id=request.pack_id,
                            message="Upgrade requires an existing installation",
                        )
                    )
                result.append(
                    LifecyclePlanStep(
                        pack_id=release.manifest.id,
                        action=action,
                        to_version=release.manifest.version,
                        content_sha256=release.content_sha256,
                        expected_row_version=existing.row_version if existing else None,
                    )
                )
                continue

            current_version = Version(existing.version)
            desired_version = Version(release.manifest.version)
            if existing.version == release.manifest.version:
                if existing.content_sha256 != release.content_sha256:
                    issues.append(
                        LifecyclePlanIssue(
                            code="registry.digest_changed",
                            pack_id=release.manifest.id,
                            message="An installed immutable release has different registry content",
                        )
                    )
                    continue
                if (
                    release.manifest.id == request.pack_id
                    and request.operation == LifecycleOperation.UPGRADE
                ):
                    issues.append(
                        LifecyclePlanIssue(
                            code="upgrade.no_change",
                            pack_id=request.pack_id,
                            message="Requested release is already installed",
                        )
                    )
                result.append(
                    LifecyclePlanStep(
                        pack_id=release.manifest.id,
                        action=PlanStepAction.NOOP,
                        from_version=existing.version,
                        to_version=existing.version,
                        content_sha256=existing.content_sha256,
                        expected_row_version=existing.row_version,
                    )
                )
                continue
            if desired_version < current_version:
                issues.append(
                    LifecyclePlanIssue(
                        code="version.downgrade_forbidden",
                        pack_id=release.manifest.id,
                        message="Pack downgrade is not supported",
                    )
                )
                continue
            if (
                release.manifest.id == request.pack_id
                and request.operation == LifecycleOperation.INSTALL
            ):
                issues.append(
                    LifecyclePlanIssue(
                        code="installation.exists",
                        pack_id=request.pack_id,
                        message="Use the upgrade operation for an installed pack",
                    )
                )
                continue
            result.append(
                LifecyclePlanStep(
                    pack_id=release.manifest.id,
                    action=PlanStepAction.UPGRADE,
                    from_version=existing.version,
                    to_version=release.manifest.version,
                    content_sha256=release.content_sha256,
                    expected_row_version=existing.row_version,
                    requires_breaking_review=desired_version.major > current_version.major,
                )
            )
        return result

    def _state_operation(
        self,
        request: LifecyclePlanRequest,
        current: dict[str, PackInstallation],
        releases: list[PackRelease],
        steps: list[LifecyclePlanStep],
        issues: list[LifecyclePlanIssue],
        organization_id: UUID,
    ) -> None:
        installation = current.get(request.pack_id)
        if installation is None or installation.state == InstallationState.UNINSTALLED:
            issues.append(
                LifecyclePlanIssue(
                    code="installation.missing",
                    pack_id=request.pack_id,
                    message="Lifecycle operation requires an installed pack",
                )
            )
            return
        action = PlanStepAction(request.operation.value)
        desired_state = self._next_state(action, installation.state)
        if action == PlanStepAction.ENABLE and desired_state == InstallationState.ENABLED:
            release = next(
                (
                    item
                    for item in releases
                    if item.manifest.id == request.pack_id
                    and item.manifest.version == installation.version
                ),
                None,
            )
            if release is None:
                issues.append(
                    LifecyclePlanIssue(
                        code="registry.installed_release_missing",
                        pack_id=request.pack_id,
                        message="Installed release is absent from the curated registry",
                    )
                )
            else:
                for dependency in release.manifest.dependencies:
                    required = current.get(dependency.id)
                    if required is None or required.state != InstallationState.ENABLED:
                        issues.append(
                            LifecyclePlanIssue(
                                code="dependency.not_enabled",
                                pack_id=dependency.id,
                                message=f"Required dependency of {request.pack_id} is not enabled",
                            )
                        )
        if action in {PlanStepAction.DISABLE, PlanStepAction.UNINSTALL}:
            if (
                action == PlanStepAction.UNINSTALL
                and installation.state == InstallationState.ENABLED
            ):
                issues.append(
                    LifecyclePlanIssue(
                        code="installation.disable_first",
                        pack_id=request.pack_id,
                        message="Disable the pack before uninstalling it",
                    )
                )
                return
            if (
                action == PlanStepAction.UNINSTALL
                and installation.state == InstallationState.ENABLED
            ):
                issues.append(
                    LifecyclePlanIssue(
                        code="installation.disable_first",
                        pack_id=request.pack_id,
                        message="Disable the pack before uninstalling it",
                    )
                )
                return
            for dependent in current.values():
                if (
                    dependent.pack_id == request.pack_id
                    or dependent.state != InstallationState.ENABLED
                ):
                    continue
                dependent_release = next(
                    (
                        item
                        for item in releases
                        if item.manifest.id == dependent.pack_id
                        and item.manifest.version == dependent.version
                    ),
                    None,
                )
                if dependent_release is None:
                    issues.append(
                        LifecyclePlanIssue(
                            code="registry.dependent_release_missing",
                            pack_id=dependent.pack_id,
                            message="Cannot verify enabled dependent pack against curated registry",
                        )
                    )
                    continue
                if any(
                    item.id == request.pack_id for item in dependent_release.manifest.dependencies
                ):
                    issues.append(
                        LifecyclePlanIssue(
                            code="installation.has_enabled_dependents",
                            pack_id=request.pack_id,
                            message=f"Enabled pack {dependent.pack_id} depends on this pack",
                        )
                    )
        if action == PlanStepAction.UNINSTALL and self.installations.has_materialized_artifacts(
            organization_id, request.pack_id
        ):
            issues.append(
                LifecyclePlanIssue(
                    code="installation.has_live_artifacts",
                    pack_id=request.pack_id,
                    message="Pack has materialized artifacts; uninstall is refused",
                )
            )
        steps.append(
            LifecyclePlanStep(
                pack_id=request.pack_id,
                action=PlanStepAction.NOOP if desired_state == installation.state else action,
                from_version=installation.version,
                to_version=installation.version,
                content_sha256=installation.content_sha256,
                expected_row_version=installation.row_version,
            )
        )

    @staticmethod
    def _next_state(action: PlanStepAction, state: InstallationState) -> InstallationState:
        if action == PlanStepAction.ENABLE:
            return InstallationState.ENABLED
        if action == PlanStepAction.DISABLE:
            return InstallationState.DISABLED
        if action == PlanStepAction.UNINSTALL:
            return InstallationState.UNINSTALLED
        if action == PlanStepAction.INSTALL:
            return InstallationState.INSTALLED
        return state

    @staticmethod
    def _resolution_issues(issues: list[ResolutionIssue]) -> list[LifecyclePlanIssue]:
        return [
            LifecyclePlanIssue(code=issue.code, pack_id=issue.pack_id, message=issue.message)
            for issue in issues
        ]

    @staticmethod
    def _plan_result(
        organization_id: UUID,
        request: LifecyclePlanRequest,
        releases: list[PackRelease],
        steps: list[LifecyclePlanStep],
        issues: list[LifecyclePlanIssue],
        current: dict[str, PackInstallation] | None = None,
    ) -> LifecyclePlan:
        valid = not issues
        digest: str | None = None
        if valid:
            payload = {
                "organization_id": str(organization_id),
                "operation": request.operation.value,
                "pack_id": request.pack_id,
                "version_range": request.version_range,
                "steps": [step.model_dump(mode="json") for step in steps],
                "releases": [
                    {
                        "id": item.manifest.id,
                        "version": item.manifest.version,
                        "sha256": item.content_sha256,
                    }
                    for item in releases
                ],
                "current": {
                    key: {
                        "version": item.version,
                        "sha256": item.content_sha256,
                        "state": item.state.value,
                        "row_version": item.row_version,
                    }
                    for key, item in sorted((current or {}).items())
                },
            }
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            digest = hashlib.sha256(canonical).hexdigest()
        return LifecyclePlan(
            organization_id=organization_id,
            operation=request.operation,
            pack_id=request.pack_id,
            valid=valid,
            plan_sha256=digest,
            selected_releases=releases,
            steps=steps,
            issues=issues,
        )
