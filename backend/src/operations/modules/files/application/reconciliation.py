"""Bounded, audited cleanup of unreferenced private upload objects."""

from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid7

from pydantic import AwareDatetime, Field

from operations.contracts import Command, ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditReader
from operations.modules.files.application.contracts import FileStore
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.organizations.application.service import OrganizationService


class StoredObject(Command):
    key: str = Field(max_length=1024)
    etag: str = Field(min_length=1, max_length=128)
    modified_at: AwareDatetime


class InventoryPage(Command):
    objects: list[StoredObject] = Field(default_factory=list, max_length=100)
    cursor: str | None = None


class CleanupPlan(Command):
    organization_id: UUID
    grace_seconds: int = Field(ge=86400, le=2592000)
    candidates: list[StoredObject] = Field(default_factory=list, max_length=100)
    scanned: int = Field(ge=0, le=100)
    cursor: str | None = None


class InventoryStorage(Protocol):
    def inventory(self, org: UUID, cursor: str | None) -> InventoryPage: ...
    def inspect(self, key: str) -> StoredObject | None: ...
    def delete_if_match(self, key: str, etag: str) -> bool: ...


CleanupOutcome = Literal["deleted", "missing", "referenced", "changed", "busy", "failed"]


def coordinates(org: UUID, key: str) -> tuple[UUID, UUID, UUID] | None:
    parts = key.split("/")
    if len(parts) != 7 or parts[:6:2] != ["organizations", "workspaces", "submissions"]:
        return None
    try:
        tenant, workspace, submission, file = (UUID(parts[i]) for i in (1, 3, 5, 6))
    except ValueError:
        return None
    if tenant != org or file.version != 7:
        return None
    canonical = f"organizations/{org}/workspaces/{workspace}/submissions/{submission}/{file}"
    return (workspace, submission, file) if canonical == key else None


class FileReconciler:
    def __init__(
        self,
        store: FileStore,
        storage: InventoryStorage,
        organizations: OrganizationService,
        evidence: AuditReader,
    ) -> None:
        self.store, self.storage = store, storage
        self.organizations, self.evidence = organizations, evidence

    def authorize(self, actor: RequestContext, org: UUID) -> UUID:
        self.organizations.active(org)
        return self.organizations.authorization.require(
            actor, "organization.manage", Scope(org, ScopeType.ORGANIZATION, org)
        ).id

    def preview(
        self,
        actor: RequestContext,
        org: UUID,
        grace_seconds: int = 86400,
        cursor: str | None = None,
    ) -> CleanupPlan:
        self.authorize(actor, org)
        plan = CleanupPlan(organization_id=org, grace_seconds=grace_seconds, scanned=0)
        page = self.storage.inventory(org, cursor)
        cutoff = datetime.now(UTC) - timedelta(seconds=grace_seconds)
        candidates = [
            item
            for item in page.objects
            if coordinates(org, item.key)
            and item.modified_at <= cutoff
            and not self.store.referenced(org, item.key)
        ]
        return plan.model_copy(
            update={"candidates": candidates, "scanned": len(page.objects), "cursor": page.cursor}
        )

    def request(self, actor: RequestContext, plan: CleanupPlan, reason: str) -> list[UUID]:
        user = self.authorize(actor, plan.organization_id)
        if not 1 <= len(reason.strip()) <= 500:
            raise ServiceError(422, "cleanup_reason_required")
        identifiers: list[UUID] = []
        for item in plan.candidates:
            location = coordinates(plan.organization_id, item.key)
            if location is None:
                raise ServiceError(422, "invalid_cleanup_object")
            workspace, submission, file = location
            identifier = uuid7()
            self.organizations.audit.append(
                AuditEvent(
                    id=identifier,
                    type="file.cleanup.requested",
                    occurred_at=datetime.now(UTC),
                    organization_id=plan.organization_id,
                    actor_id=user,
                    correlation_id=actor.correlation_id,
                    request_id=actor.request_id,
                    aggregate_type="file",
                    aggregate_id=file,
                    payload=AuditDetails(
                        reason=reason.strip(),
                        workspace_id=workspace,
                        submission_id=submission,
                        storage_etag=item.etag,
                        storage_modified_at=item.modified_at,
                        storage_grace_seconds=plan.grace_seconds,
                    ),
                )
            )
            identifiers.append(identifier)
        return identifiers

    def apply(self, actor: RequestContext, org: UUID, intent_id: UUID) -> CleanupOutcome:
        # The CLI commits requested evidence in a separate transaction before this call.
        user = self.authorize(actor, org)
        intent = self.evidence.get(org, intent_id)
        if intent is None or intent.type != "file.cleanup.requested" or intent.actor_id != user:
            raise ServiceError(404, "cleanup_intent_not_found")
        data = intent.payload
        if not (
            data.workspace_id
            and data.submission_id
            and intent.aggregate_id
            and data.storage_etag
            and data.storage_modified_at
            and data.storage_grace_seconds
        ):
            raise ServiceError(422, "invalid_cleanup_intent")
        key = (
            f"organizations/{org}/workspaces/{data.workspace_id}/"
            f"submissions/{data.submission_id}/{intent.aggregate_id}"
        )
        if not self.store.lock_key(key):
            return self.finish(actor, org, user, intent, "busy")
        if self.store.referenced(org, key):
            return self.finish(actor, org, user, intent, "referenced")
        try:
            current = self.storage.inspect(key)
            if current is None:
                outcome: CleanupOutcome = "missing"
            elif (
                current.etag != data.storage_etag
                or current.modified_at != data.storage_modified_at
                or current.modified_at
                > datetime.now(UTC) - timedelta(seconds=data.storage_grace_seconds)
            ):
                outcome = "changed"
            else:
                outcome = (
                    "deleted" if self.storage.delete_if_match(key, current.etag) else "changed"
                )
        except ServiceError:
            outcome = "failed"
        return self.finish(actor, org, user, intent, outcome)

    def finish(
        self,
        actor: RequestContext,
        org: UUID,
        user: UUID,
        intent: AuditEvent,
        outcome: CleanupOutcome,
    ) -> CleanupOutcome:
        self.organizations.audit.append(
            AuditEvent(
                id=uuid7(),
                type="file.cleanup.result",
                occurred_at=datetime.now(UTC),
                organization_id=org,
                actor_id=user,
                correlation_id=intent.correlation_id,
                request_id=actor.request_id,
                aggregate_type="file",
                aggregate_id=intent.aggregate_id,
                payload=AuditDetails(
                    target_id=intent.id,
                    outcome=outcome,
                    workspace_id=intent.payload.workspace_id,
                    submission_id=intent.payload.submission_id,
                ),
            )
        )
        return outcome
