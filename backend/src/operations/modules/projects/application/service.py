from datetime import UTC, datetime
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.iam.application.service import Authorization
from operations.modules.identity.application.contracts import IdentityStore, RequestContext, User
from operations.modules.master_data.application.contracts import MasterDataReader
from operations.modules.projects.application.contracts import (
    DepartmentProjectGrant,
    LifecycleDefinition,
    Project,
    ProjectContext,
    ProjectMembership,
    ProjectRole,
    ProjectStore,
)
from operations.modules.workspaces.application.groups import GroupReader
from operations.modules.workspaces.application.service import WorkspaceService

PROJECT_PERMISSIONS = {
    ProjectRole.MANAGER: frozenset(
        {
            "form.read",
            "form.manage",
            "form.publish",
            "submission.create",
            "submission.read",
            "project.read",
            "project.manage",
            "project.members.manage",
            "master_data.read",
            "master_data.manage",
        }
    ),
    ProjectRole.VIEWER: frozenset({"project.read", "master_data.read", "form.read"}),
    ProjectRole.CONTRIBUTOR: frozenset(
        {"project.read", "master_data.read", "form.read", "submission.create"}
    ),
}


def effective(grant: ProjectMembership | DepartmentProjectGrant, now: datetime) -> bool:
    return (
        not grant.revoked
        and (grant.valid_from is None or now >= grant.valid_from)
        and (grant.valid_until is None or now < grant.valid_until)
    )


class ProjectService:
    def __init__(
        self,
        store: ProjectStore,
        workspaces: WorkspaceService,
        groups: GroupReader,
        authorization: Authorization,
        identities: IdentityStore,
        references: MasterDataReader,
        audit: AuditWriter,
    ) -> None:
        (
            self.store,
            self.workspaces,
            self.groups,
            self.authorization,
            self.identities,
            self.references,
            self.audit,
        ) = store, workspaces, groups, authorization, identities, references, audit

    def allowed(
        self, context: RequestContext, organization_id: UUID, workspace_id: UUID, project_id: UUID
    ) -> frozenset[str]:
        self.workspaces.active(organization_id, workspace_id)
        actor = self.authorization.user(context, organization_id)
        if "project.admin" in self.authorization.allowed(
            context, Scope(organization_id, ScopeType.WORKSPACE, workspace_id)
        ):
            return PROJECT_PERMISSIONS[ProjectRole.MANAGER]
        now = datetime.now(UTC)
        result: set[str] = set()
        for membership in self.store.memberships(organization_id, actor.id):
            if (
                membership.workspace_id == workspace_id
                and membership.project_id == project_id
                and effective(membership, now)
            ):
                result.update(PROJECT_PERMISSIONS[membership.role])
        departments = self.groups.departments_for_user(organization_id, workspace_id, actor.id)
        for grant in self.store.department_grants(organization_id, departments):
            if (
                grant.workspace_id == workspace_id
                and grant.project_id == project_id
                and effective(grant, now)
            ):
                result.update(PROJECT_PERMISSIONS[grant.role])
        return frozenset(result)

    def workspace_ids(self, context: RequestContext, organization_id: UUID) -> list[UUID]:
        actor = self.authorization.user(context, organization_id)
        now = datetime.now(UTC)
        visible = {
            member.workspace_id
            for member in self.store.memberships(organization_id, actor.id)
            if effective(member, now)
        }
        visible.update(self.groups.workspace_ids(organization_id, actor.id))
        return list(visible)

    def revoke_user_access(
        self, context: RequestContext, organization_id: UUID, user_id: UUID
    ) -> None:
        self.authorization.require(
            context,
            "organization.members.manage",
            Scope(organization_id, ScopeType.ORGANIZATION, organization_id),
        )
        for member in self.store.memberships(organization_id, user_id):
            if not member.revoked:
                project = self.store.get(organization_id, member.workspace_id, member.project_id)
                if project is None:
                    raise ServiceError(409, "missing_project_history")
                self.store.revoke_membership(organization_id, member.id)
                self.event(context, project, "project.member.revoked", member.id)

    def require_access(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        permission: str,
    ) -> Project:
        if permission not in self.allowed(context, organization_id, workspace_id, project_id):
            raise ServiceError(403, "access_denied")
        project = self.store.get(organization_id, workspace_id, project_id)
        if project is None:
            raise ServiceError(404, "not_found")
        return project

    def event(
        self,
        context: RequestContext,
        project: Project,
        action: str,
        identifier: UUID | None = None,
        reason: str | None = None,
    ) -> None:
        actor = self.authorization.user(context, project.organization_id)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type=action,
                occurred_at=datetime.now(UTC),
                organization_id=project.organization_id,
                actor_id=actor.id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="project",
                aggregate_id=project.id,
                payload=AuditDetails(target_id=identifier, version=project.version, reason=reason),
            )
        )

    def create(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        name: str,
        details: ProjectContext,
        lifecycle: LifecycleDefinition,
    ) -> Project:
        self.workspaces.active(organization_id, workspace_id)
        actor = self.authorization.require(
            context, "project.create", Scope(organization_id, ScopeType.WORKSPACE, workspace_id)
        )
        self.references.project_references(
            organization_id, workspace_id, None, details.location_ids, details.asset_ids
        )
        project = Project(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=name,
            state=lifecycle.initial,
            lifecycle=lifecycle,
            context=details,
            version=1,
        )
        self.store.create(project)
        membership = ProjectMembership(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            project_id=project.id,
            user_id=actor.id,
            role=ProjectRole.MANAGER,
        )
        self.store.add_membership(membership)
        self.event(context, project, "project.created")
        self.event(context, project, "project.member.added", membership.id)
        return project

    def update(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        name: str,
        details: ProjectContext,
        expected_version: int,
    ) -> Project:
        project = self.require_access(
            context, organization_id, workspace_id, project_id, "project.manage"
        )
        if project.state in project.lifecycle.terminal:
            raise ServiceError(409, "project_terminal")
        self.references.project_references(
            organization_id, workspace_id, project_id, details.location_ids, details.asset_ids
        )
        changed = project.model_copy(
            update={"name": name, "context": details, "version": expected_version + 1}
        )
        if not self.store.update(changed, expected_version):
            raise ServiceError(409, "version_conflict")
        self.event(context, changed, "project.updated")
        return changed

    def transition(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        state: str,
        expected_version: int,
        reason: str,
        dry_run: bool = False,
    ) -> Project:
        project = self.require_access(
            context, organization_id, workspace_id, project_id, "project.manage"
        )
        if project.version != expected_version:
            raise ServiceError(409, "version_conflict")
        if not project.lifecycle.policy().allows(project.state, state):
            raise ServiceError(422, "invalid_transition")
        changed = project.model_copy(update={"state": state, "version": project.version + 1})
        if dry_run:
            return changed
        if not self.store.update(changed, expected_version):
            raise ServiceError(409, "version_conflict")
        self.event(context, changed, "project.transitioned", reason=reason)
        return changed

    def list_projects(
        self, context: RequestContext, organization_id: UUID, workspace_id: UUID, after: UUID | None
    ) -> list[Project]:
        self.workspaces.active(organization_id, workspace_id)
        actor = self.authorization.user(context, organization_id)
        if "project.admin" in self.authorization.allowed(
            context, Scope(organization_id, ScopeType.WORKSPACE, workspace_id)
        ):
            return self.store.list_projects(organization_id, workspace_id, None, after)
        now = datetime.now(UTC)
        visible = {
            m.project_id
            for m in self.store.memberships(organization_id, actor.id)
            if m.workspace_id == workspace_id and effective(m, now)
        }
        departments = self.groups.departments_for_user(organization_id, workspace_id, actor.id)
        visible.update(
            g.project_id
            for g in self.store.department_grants(organization_id, departments)
            if g.workspace_id == workspace_id and effective(g, now)
        )
        return self.store.list_projects(organization_id, workspace_id, list(visible), after)

    def check_grant(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        role: ProjectRole,
        valid_from: datetime | None,
        valid_until: datetime | None,
    ) -> Project:
        project = self.require_access(
            context, organization_id, workspace_id, project_id, "project.members.manage"
        )
        if not PROJECT_PERMISSIONS[role] <= self.allowed(
            context, organization_id, workspace_id, project_id
        ):
            raise ServiceError(403, "privilege_escalation")
        if valid_from and valid_until and valid_until <= valid_from:
            raise ServiceError(422, "invalid_validity_window")
        if project.state in project.lifecycle.terminal:
            raise ServiceError(409, "project_terminal")
        return project

    def membership_candidates(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        email: str,
    ) -> list[User]:
        self.require_access(
            context, organization_id, workspace_id, project_id, "project.members.manage"
        )
        return self.identities.active_by_email(organization_id, email)

    def add_member(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        user_id: UUID,
        role: ProjectRole,
        valid_from: datetime | None,
        valid_until: datetime | None,
    ) -> ProjectMembership:
        project = self.check_grant(
            context, organization_id, workspace_id, project_id, role, valid_from, valid_until
        )
        actor = self.authorization.user(context, organization_id)
        target = self.identities.by_id(organization_id, user_id)
        if target is None or not target.active:
            raise ServiceError(404, "not_found")
        if user_id == actor.id:
            raise ServiceError(403, "privilege_escalation")
        membership = ProjectMembership(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            role=role,
            valid_from=valid_from,
            valid_until=valid_until,
        )
        self.store.add_membership(membership)
        self.event(context, project, "project.member.added", membership.id)
        return membership

    def revoke_member(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        member_id: UUID,
    ) -> None:
        project = self.require_access(
            context, organization_id, workspace_id, project_id, "project.members.manage"
        )
        membership = self.store.membership(organization_id, project_id, member_id)
        if membership is None:
            raise ServiceError(404, "not_found")
        if membership.user_id == self.authorization.user(context, organization_id).id:
            raise ServiceError(403, "privilege_escalation")
        self.store.revoke_membership(organization_id, member_id)
        self.event(context, project, "project.member.revoked", member_id)

    def grant_department(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        department_id: UUID,
        role: ProjectRole,
        valid_from: datetime | None,
        valid_until: datetime | None,
    ) -> DepartmentProjectGrant:
        project = self.check_grant(
            context, organization_id, workspace_id, project_id, role, valid_from, valid_until
        )
        self.groups.active_department(organization_id, workspace_id, department_id)
        actor = self.authorization.user(context, organization_id)
        if department_id in self.groups.departments_for_user(
            organization_id, workspace_id, actor.id
        ):
            raise ServiceError(403, "privilege_escalation")
        grant = DepartmentProjectGrant(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            project_id=project_id,
            department_id=department_id,
            role=role,
            valid_from=valid_from,
            valid_until=valid_until,
        )
        self.store.add_department_grant(grant)
        self.event(context, project, "project.department_grant.created", grant.id)
        return grant

    def revoke_department(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        grant_id: UUID,
    ) -> None:
        project = self.require_access(
            context, organization_id, workspace_id, project_id, "project.members.manage"
        )
        grant = self.store.department_grant(organization_id, project_id, grant_id)
        if grant is None:
            raise ServiceError(404, "not_found")
        if grant.department_id in self.groups.departments_for_user(
            organization_id, workspace_id, self.authorization.user(context, organization_id).id
        ):
            raise ServiceError(403, "privilege_escalation")
        self.store.revoke_department_grant(organization_id, grant_id)
        self.event(context, project, "project.department_grant.revoked", grant_id)
