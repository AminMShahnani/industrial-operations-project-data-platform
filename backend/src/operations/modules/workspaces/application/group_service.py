from datetime import UTC, datetime
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.iam.application.service import Authorization
from operations.modules.identity.application.contracts import IdentityStore, RequestContext, User
from operations.modules.workspaces.application.groups import (
    Group,
    GroupKind,
    GroupMembership,
    GroupStore,
)
from operations.modules.workspaces.application.service import WorkspaceService


class GroupService:
    def __init__(
        self,
        store: GroupStore,
        workspaces: WorkspaceService,
        authorization: Authorization,
        identities: IdentityStore,
        audit: AuditWriter,
    ) -> None:
        self.store, self.workspaces, self.authorization, self.identities, self.audit = (
            store,
            workspaces,
            authorization,
            identities,
            audit,
        )

    def event(
        self, context: RequestContext, group: Group, action: str, identifier: UUID | None = None
    ) -> None:
        actor = self.authorization.user(context, group.organization_id)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type=action,
                occurred_at=datetime.now(UTC),
                organization_id=group.organization_id,
                actor_id=actor.id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="workspace_group",
                aggregate_id=group.id,
                payload=AuditDetails(target_id=identifier, version=group.version),
            )
        )

    def revoke_user_access(
        self, context: RequestContext, organization_id: UUID, user_id: UUID
    ) -> None:
        self.authorization.require(
            context,
            "organization.members.manage",
            Scope(organization_id, ScopeType.ORGANIZATION, organization_id),
        )
        for member in self.store.active_memberships_for_user(organization_id, user_id):
            group = self.store.get(organization_id, member.workspace_id, member.group_id)
            if group is None:
                raise ServiceError(409, "missing_group_history")
            self.store.revoke(organization_id, member.id)
            self.event(context, group, "workspace_group.member.revoked", member.id)

    def create(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        kind: GroupKind,
        name: str,
    ) -> Group:
        self.workspaces.active(organization_id, workspace_id)
        self.authorization.require(
            context, "department.manage", Scope(organization_id, ScopeType.WORKSPACE, workspace_id)
        )
        group = Group(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            kind=kind,
            name=name,
        )
        self.store.create(group)
        self.event(context, group, "workspace_group.created")
        return group

    def get(self, organization_id: UUID, workspace_id: UUID, group_id: UUID) -> Group:
        self.workspaces.active(organization_id, workspace_id)
        group = self.store.get(organization_id, workspace_id, group_id)
        if group is None:
            raise ServiceError(404, "not_found")
        return group

    def active_department(self, organization_id: UUID, workspace_id: UUID, group_id: UUID) -> Group:
        group = self.get(organization_id, workspace_id, group_id)
        if not group.active or group.kind != GroupKind.DEPARTMENT:
            raise ServiceError(404, "not_found")
        return group

    def departments_for_user(
        self, organization_id: UUID, workspace_id: UUID, user_id: UUID
    ) -> list[UUID]:
        return [
            member.group_id
            for member in self.store.memberships(organization_id, workspace_id, user_id)
            if (group := self.store.get(organization_id, workspace_id, member.group_id)) is not None
            and group.active
            and group.kind == GroupKind.DEPARTMENT
        ]

    def department_workspaces(self, organization_id: UUID, user_id: UUID) -> dict[UUID, list[UUID]]:
        result: dict[UUID, list[UUID]] = {}
        for member in self.store.active_memberships_for_user(organization_id, user_id):
            group = self.store.get(organization_id, member.workspace_id, member.group_id)
            if group is not None and group.active and group.kind == GroupKind.DEPARTMENT:
                result.setdefault(member.workspace_id, []).append(group.id)
        return result

    def require_manager(self, context: RequestContext, group: Group) -> None:
        if "department.manage" in self.authorization.allowed(
            context, Scope(group.organization_id, ScopeType.WORKSPACE, group.workspace_id)
        ):
            return
        actor = self.authorization.user(context, group.organization_id)
        if group.active and any(
            member.group_id == group.id and member.manager
            for member in self.store.memberships(
                group.organization_id, group.workspace_id, actor.id
            )
        ):
            return
        raise ServiceError(403, "access_denied")

    def update(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        group_id: UUID,
        name: str,
        active: bool,
        expected_version: int,
    ) -> Group:
        group = self.get(organization_id, workspace_id, group_id)
        self.require_manager(context, group)
        changed = group.model_copy(
            update={"name": name, "active": active, "version": expected_version + 1}
        )
        if not self.store.update(changed, expected_version):
            raise ServiceError(409, "version_conflict")
        self.event(context, changed, "workspace_group.updated")
        return changed

    def list_groups(
        self, context: RequestContext, organization_id: UUID, workspace_id: UUID, after: UUID | None
    ) -> list[Group]:
        self.workspaces.active(organization_id, workspace_id)
        actor = self.authorization.user(context, organization_id)
        visible = None
        if "workspace.read" not in self.authorization.allowed(
            context, Scope(organization_id, ScopeType.WORKSPACE, workspace_id)
        ):
            visible = [
                member.group_id
                for member in self.store.memberships(organization_id, workspace_id, actor.id)
            ]
        return self.store.list_groups(organization_id, workspace_id, after, visible)

    def workspace_ids(self, organization_id: UUID, user_id: UUID) -> list[UUID]:
        return list(
            {
                member.workspace_id
                for member in self.store.active_memberships_for_user(organization_id, user_id)
                if (group := self.store.get(organization_id, member.workspace_id, member.group_id))
                is not None
                and group.active
            }
        )

    def add_member(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        group_id: UUID,
        user_id: UUID,
        manager: bool,
    ) -> GroupMembership:
        group = self.get(organization_id, workspace_id, group_id)
        self.require_manager(context, group)
        actor = self.authorization.user(context, organization_id)
        target = self.identities.by_id(organization_id, user_id)
        if target is None or not target.active or not group.active:
            raise ServiceError(404, "not_found")
        if user_id == actor.id:
            raise ServiceError(403, "privilege_escalation")
        membership = GroupMembership(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            group_id=group_id,
            user_id=user_id,
            manager=manager,
        )
        self.store.add_membership(membership)
        self.event(context, group, "workspace_group.member.added", membership.id)
        return membership

    def membership_candidates(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        group_id: UUID,
        email: str,
    ) -> list[User]:
        group = self.get(organization_id, workspace_id, group_id)
        self.require_manager(context, group)
        return self.identities.active_by_email(organization_id, email)

    def management_permissions(
        self, context: RequestContext, organization_id: UUID, workspace_id: UUID, group_id: UUID
    ) -> list[str]:
        group = self.get(organization_id, workspace_id, group_id)
        try:
            self.require_manager(context, group)
            return ["group.manage"]
        except ServiceError as error:
            if error.status != 403:
                raise
            return []

    def revoke(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        group_id: UUID,
        member_id: UUID,
    ) -> None:
        group = self.get(organization_id, workspace_id, group_id)
        self.require_manager(context, group)
        member = self.store.membership(organization_id, group_id, member_id)
        actor = self.authorization.user(context, organization_id)
        if member is None:
            raise ServiceError(404, "not_found")
        if member.user_id == actor.id:
            raise ServiceError(403, "privilege_escalation")
        self.store.revoke(organization_id, member_id)
        self.event(context, group, "workspace_group.member.revoked", member_id)
