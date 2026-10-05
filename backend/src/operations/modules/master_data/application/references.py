from datetime import UTC, datetime
from uuid import UUID

from operations.contracts import ServiceError
from operations.modules.master_data.application.contracts import (
    DataRecord,
    DataStore,
    DataType,
    RecordStatus,
    RegistryKind,
)


def visible_at(
    definition: DataType,
    organization_id: UUID | None,
    workspace_id: UUID | None,
    project_id: UUID | None,
) -> bool:
    return (
        (definition.organization_id is None or definition.organization_id == organization_id)
        and (definition.workspace_id is None or definition.workspace_id == workspace_id)
        and (definition.project_id is None or definition.project_id == project_id)
    )


def record_active(record: DataRecord) -> bool:
    today = datetime.now(UTC).date()
    return (
        record.status == RecordStatus.ACTIVE
        and (record.valid_from is None or today >= record.valid_from)
        and (record.valid_until is None or today <= record.valid_until)
    )


class DataReferences:
    def __init__(self, store: DataStore) -> None:
        self.store = store

    def require(
        self,
        organization_id: UUID | None,
        workspace_id: UUID | None,
        project_id: UUID | None,
        record_id: UUID,
        type_id: UUID | None = None,
        registry: RegistryKind | None = None,
    ) -> DataRecord:
        record = self.store.record(organization_id, record_id) or self.store.record(None, record_id)
        definition = self.store.type(record.organization_id, record.type_id) if record else None
        if (
            record is None
            or definition is None
            or not definition.active
            or not record_active(record)
            or not visible_at(definition, organization_id, workspace_id, project_id)
        ):
            raise ServiceError(422, "invalid_master_data_reference")
        if (type_id and definition.id != type_id) or (registry and definition.registry != registry):
            raise ServiceError(422, "invalid_master_data_reference")
        return record

    def project_references(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None,
        location_ids: list[UUID],
        asset_ids: list[UUID],
    ) -> None:
        for record_id in location_ids:
            self.require(
                organization_id, workspace_id, project_id, record_id, registry=RegistryKind.LOCATION
            )
        for record_id in asset_ids:
            self.require(
                organization_id, workspace_id, project_id, record_id, registry=RegistryKind.ASSET
            )

    def lookup(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None,
        type_id: UUID,
        cursor: UUID | None,
    ) -> tuple[list[DataRecord], UUID | None]:
        definition = self.store.type(organization_id, type_id) or self.store.type(None, type_id)
        if (
            not definition
            or not definition.active
            or not visible_at(definition, organization_id, workspace_id, project_id)
        ):
            raise ServiceError(422, "invalid_master_data_reference")
        rows = self.store.list_records(definition.organization_id, type_id, cursor)
        return [row for row in rows[:100] if record_active(row)], rows[99].id if len(
            rows
        ) > 100 else None
