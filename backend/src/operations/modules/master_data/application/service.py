import re
from contextlib import suppress
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.automation.application.events import EventContext
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.iam.application.service import Authorization
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.master_data.application.contracts import (
    DataRecord,
    DataSchema,
    DataScope,
    DataStore,
    DataType,
    FieldKind,
    RecordStatus,
    RecordValues,
    RegistryKind,
)
from operations.modules.master_data.application.references import DataReferences, visible_at
from operations.modules.organizations.application.contracts import OrganizationReader
from operations.modules.projects.application.contracts import Project
from operations.modules.workspaces.application.service import WorkspaceService


class ProjectAccess(Protocol):
    def require_access(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        permission: str,
    ) -> Project: ...


class MasterDataService:
    def __init__(
        self,
        store: DataStore,
        organizations: OrganizationReader,
        workspaces: WorkspaceService,
        projects: ProjectAccess,
        authorization: Authorization,
        references: DataReferences,
        audit: AuditWriter,
    ) -> None:
        (
            self.store,
            self.organizations,
            self.workspaces,
            self.projects,
            self.authorization,
            self.references,
            self.audit,
        ) = store, organizations, workspaces, projects, authorization, references, audit

    def access(
        self,
        context: RequestContext,
        organization_id: UUID,
        definition: DataType,
        write: bool = False,
    ) -> None:
        self.organizations.active(organization_id)
        self.authorization.user(context, organization_id)
        if definition.organization_id is None:
            if write:
                raise ServiceError(403, "global_reference_read_only")
            return
        if definition.organization_id != organization_id:
            raise ServiceError(403, "access_denied")
        permission = "master_data.manage" if write else "master_data.read"
        if definition.project_id and definition.workspace_id:
            project = self.projects.require_access(
                context, organization_id, definition.workspace_id, definition.project_id, permission
            )
            if write and project.state in project.lifecycle.terminal:
                raise ServiceError(409, "project_terminal")
        elif definition.workspace_id:
            self.workspaces.active(organization_id, definition.workspace_id)
            self.authorization.require(
                context,
                permission,
                Scope(organization_id, ScopeType.WORKSPACE, definition.workspace_id),
            )
        else:
            self.authorization.require(
                context, permission, Scope(organization_id, ScopeType.ORGANIZATION, organization_id)
            )

    def definition(
        self, context: RequestContext, organization_id: UUID, type_id: UUID, write: bool = False
    ) -> DataType:
        definition = self.store.type(organization_id, type_id) or self.store.type(None, type_id)
        if definition is None:
            raise ServiceError(404, "not_found")
        self.access(context, organization_id, definition, write)
        return definition

    def list_types(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID | None,
        project_id: UUID | None,
        cursor: UUID | None,
    ) -> tuple[list[DataType], UUID | None]:
        self.organizations.active(organization_id)
        self.authorization.user(context, organization_id)
        if project_id and not workspace_id:
            raise ServiceError(422, "invalid_master_data_scope")
        if workspace_id:
            self.workspaces.active(organization_id, workspace_id)
        if project_id and workspace_id:
            self.projects.require_access(
                context, organization_id, workspace_id, project_id, "project.read"
            )
        candidates = self.store.list_types(organization_id, workspace_id, project_id, cursor)
        visible: list[DataType] = []
        for definition in candidates[:100]:
            try:
                self.access(context, organization_id, definition)
                visible.append(definition)
            except ServiceError as error:
                if error.status != 403:
                    raise
        return visible, candidates[99].id if len(candidates) > 100 else None

    def event(
        self,
        context: RequestContext,
        organization_id: UUID | None,
        action: str,
        identifier: UUID,
        version: int,
        reason: str | None = None,
        *,
        workspace_id: UUID | None = None,
        project_id: UUID | None = None,
        source: EventContext | None = None,
    ) -> None:
        actor_id = self.authorization.user(context, organization_id).id if organization_id else None
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type=action,
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor_id=actor_id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="master_data",
                aggregate_id=identifier,
                payload=AuditDetails(
                    version=version,
                    reason=reason,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    **(source.model_dump() if source else {}),
                ),
            )
        )

    def schema_references(self, definition: DataType) -> None:
        for field in definition.definition.fields:
            if field.reference_type_id:
                target = self.store.type(
                    definition.organization_id, field.reference_type_id
                ) or self.store.type(None, field.reference_type_id)
                if (
                    target is None
                    or not target.active
                    or not visible_at(
                        target,
                        definition.organization_id,
                        definition.workspace_id,
                        definition.project_id,
                    )
                ):
                    raise ServiceError(422, "invalid_reference_type")

    def create_type(
        self,
        context: RequestContext,
        organization_id: UUID,
        scope: DataScope,
        workspace_id: UUID | None,
        project_id: UUID | None,
        code: str,
        name: str,
        registry: RegistryKind,
        schema: DataSchema,
    ) -> DataType:
        if scope == DataScope.GLOBAL:
            raise ServiceError(403, "global_reference_read_only")
        if (scope in {DataScope.WORKSPACE, DataScope.PROJECT}) != (workspace_id is not None) or (
            scope == DataScope.PROJECT
        ) != (project_id is not None):
            raise ServiceError(422, "invalid_master_data_scope")
        definition = DataType(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            project_id=project_id,
            scope=scope,
            code=code,
            name=name,
            registry=registry,
            definition=schema,
        )
        self.access(context, organization_id, definition, True)
        self.schema_references(definition)
        self.store.create_type(definition)
        self.event(
            context, organization_id, "master_data.type.created", definition.id, definition.version
        )
        return definition

    def validate(self, definition: DataType, record: DataRecord) -> None:
        if (
            not definition.active
            or record.type_id != definition.id
            or record.organization_id != definition.organization_id
        ):
            raise ServiceError(422, "invalid_master_data_record")
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,59}", record.code)
            or not record.name.strip()
            or len(record.name) > 120
        ):
            raise ServiceError(422, "invalid_master_data_record")
        if record.valid_from and record.valid_until and record.valid_until < record.valid_from:
            raise ServiceError(422, "invalid_validity_window")
        fields = {field.key: field for field in definition.definition.fields}
        if record.values.fields.keys() - fields.keys():
            raise ServiceError(422, "unknown_master_data_field")
        for key, field in fields.items():
            value = record.values.fields.get(key)
            if value is None:
                if field.required:
                    raise ServiceError(422, "required_master_data_field")
                continue
            valid = False
            if field.kind == FieldKind.TEXT:
                valid = isinstance(value, str) and len(value) <= 2000
            elif field.kind == FieldKind.INTEGER:
                valid = type(value) is int and -(2**63) <= value < 2**63
            elif field.kind == FieldKind.BOOLEAN:
                valid = type(value) is bool
            elif field.kind == FieldKind.ENUM:
                valid = isinstance(value, str) and value in field.choices
            elif field.kind == FieldKind.DECIMAL:
                if isinstance(value, str) and re.fullmatch(r"-?\d{1,18}(\.\d{1,6})?", value):
                    with suppress(InvalidOperation):
                        valid = Decimal(value).is_finite()
            elif field.kind == FieldKind.DATE:
                if isinstance(value, str):
                    with suppress(ValueError):
                        valid = date.fromisoformat(value).isoformat() == value
            elif field.kind == FieldKind.REFERENCE and isinstance(value, str):
                try:
                    self.references.require(
                        definition.organization_id,
                        definition.workspace_id,
                        definition.project_id,
                        UUID(value),
                        type_id=field.reference_type_id,
                    )
                    valid = True
                except ValueError:
                    pass
            if not valid:
                raise ServiceError(422, "invalid_master_data_value")

    def create_record(
        self,
        context: RequestContext,
        organization_id: UUID,
        type_id: UUID,
        code: str,
        name: str,
        status: RecordStatus,
        valid_from: date | None,
        valid_until: date | None,
        values: RecordValues,
    ) -> DataRecord:
        definition = self.definition(context, organization_id, type_id, True)
        record = DataRecord(
            id=uuid7(),
            organization_id=organization_id,
            type_id=type_id,
            code=code,
            name=name,
            status=status,
            valid_from=valid_from,
            valid_until=valid_until,
            values=values,
        )
        self.validate(definition, record)
        if self.store.by_code(organization_id, type_id, code):
            raise ServiceError(409, "duplicate_master_data_code")
        self.store.create_record(record)
        self.event(
            context,
            organization_id,
            "master_data.record.created",
            record.id,
            record.version,
            workspace_id=definition.workspace_id,
            project_id=definition.project_id,
            source=EventContext(master_data_type_id=type_id, master_data_record_id=record.id),
        )
        return record

    def update_record(
        self,
        context: RequestContext,
        organization_id: UUID,
        type_id: UUID,
        record_id: UUID,
        name: str,
        status: RecordStatus,
        valid_from: date | None,
        valid_until: date | None,
        values: RecordValues,
        expected_version: int,
    ) -> DataRecord:
        definition = self.definition(context, organization_id, type_id, True)
        record = self.store.record(organization_id, record_id)
        if record is None or record.type_id != type_id:
            raise ServiceError(404, "not_found")
        changed = record.model_copy(
            update={
                "name": name,
                "status": status,
                "valid_from": valid_from,
                "valid_until": valid_until,
                "values": values,
                "version": expected_version + 1,
            }
        )
        self.validate(definition, changed)
        if not self.store.update_record(changed, expected_version):
            raise ServiceError(409, "version_conflict")
        self.event(
            context,
            organization_id,
            "master_data.record.updated",
            record_id,
            changed.version,
            workspace_id=definition.workspace_id,
            project_id=definition.project_id,
            source=EventContext(master_data_type_id=type_id, master_data_record_id=record_id),
        )
        return changed

    def publish_global(
        self,
        context: RequestContext,
        definition: DataType,
        records: list[DataRecord],
        reason: str,
        dry_run: bool = False,
    ) -> None:
        # Operator composition only: deliberately no HTTP route or role-based entry point.
        if not self.authorization.identities.platform_admin(context.principal):
            raise ServiceError(403, "access_denied")
        if (
            definition.organization_id is not None
            or definition.scope != DataScope.GLOBAL
            or definition.workspace_id
            or definition.project_id
        ):
            raise ServiceError(422, "invalid_global_scope")
        if not reason.strip() or len(reason) > 500:
            raise ServiceError(422, "publication_reason_required")
        self.schema_references(definition)
        if len(records) > 1000 or len({record.code for record in records}) != len(records):
            raise ServiceError(422, "invalid_global_records")
        for record in records:
            self.validate(definition, record)
        if dry_run:
            return
        self.store.create_type(definition)
        self.event(
            context,
            None,
            "master_data.global_type.published",
            definition.id,
            definition.version,
            reason,
        )
        for record in records:
            self.store.create_record(record)
            self.event(
                context,
                None,
                "master_data.global_record.published",
                record.id,
                record.version,
                reason,
            )
