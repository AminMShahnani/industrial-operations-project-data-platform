from datetime import date
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.master_data.application.contracts import (
    DataRecord,
    DataSchema,
    DataScope,
    DataType,
    RecordStatus,
    RecordValues,
    RegistryKind,
)
from operations.platform.database import Base

GLOBAL_OWNER = UUID(int=0)


class DataTypeRow(Base):
    __tablename__ = "master_data_types"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        UniqueConstraint("owner_id", "id", name="uq_master_data_types_owner_identity"),
        UniqueConstraint("owner_id", "scope_id", "code", name="uq_master_data_types_scope_code"),
        CheckConstraint(
            "(scope = 'global' AND organization_id IS NULL AND owner_id = "
            "'00000000-0000-0000-0000-000000000000' AND scope_id = owner_id AND "
            "workspace_id IS NULL AND project_id IS NULL) OR (organization_id IS NOT "
            "NULL AND owner_id = organization_id AND organization_id <> "
            "'00000000-0000-0000-0000-000000000000' AND ((scope = 'organization' AND "
            "scope_id = organization_id AND workspace_id IS NULL AND project_id IS NULL) "
            "OR (scope = 'workspace' AND workspace_id IS NOT NULL AND scope_id = "
            "workspace_id AND project_id IS NULL) OR (scope = 'project' AND workspace_id "
            "IS NOT NULL AND project_id IS NOT NULL AND scope_id = project_id)))",
            name="data_type_scope",
        ),
        Index("ix_master_data_types_scope", "organization_id", "workspace_id", "project_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"))
    owner_id: Mapped[UUID]
    scope_id: Mapped[UUID]
    workspace_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    scope: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(120))
    registry_kind: Mapped[str] = mapped_column("registry", String(20))
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    active: Mapped[bool]
    version: Mapped[int]


class DataRecordRow(Base):
    __tablename__ = "master_data_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "type_id"], ["master_data_types.owner_id", "master_data_types.id"]
        ),
        CheckConstraint(
            "(organization_id IS NULL AND owner_id = "
            "'00000000-0000-0000-0000-000000000000') OR (organization_id IS NOT NULL AND "
            "owner_id = organization_id AND organization_id <> "
            "'00000000-0000-0000-0000-000000000000')",
            name="data_record_owner",
        ),
        CheckConstraint("status IN ('active', 'inactive', 'deprecated')", name="record_status"),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="record_validity",
        ),
        UniqueConstraint("owner_id", "type_id", "code", name="uq_master_data_records_type_code"),
        Index("ix_master_data_records_scope_status", "organization_id", "type_id", "status", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"))
    owner_id: Mapped[UUID]
    type_id: Mapped[UUID]
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    values: Mapped[dict[str, object]] = mapped_column(JSONB)
    version: Mapped[int]


def type_contract(row: DataTypeRow) -> DataType:
    return DataType(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        scope=DataScope(row.scope),
        code=row.code,
        name=row.name,
        registry=RegistryKind(row.registry_kind),
        definition=DataSchema.model_validate(row.definition),
        active=row.active,
        version=row.version,
    )


def record_contract(row: DataRecordRow) -> DataRecord:
    return DataRecord(
        id=row.id,
        organization_id=row.organization_id,
        type_id=row.type_id,
        code=row.code,
        name=row.name,
        status=RecordStatus(row.status),
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        values=RecordValues.model_validate(row.values),
        version=row.version,
    )


class DataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def type(self, organization_id: UUID | None, type_id: UUID) -> DataType | None:
        row = self.session.scalar(
            select(DataTypeRow)
            .where(DataTypeRow.organization_id == organization_id, DataTypeRow.id == type_id)
            .with_for_update()
        )
        return type_contract(row) if row else None

    def create_type(self, definition: DataType) -> None:
        owner = definition.organization_id or GLOBAL_OWNER
        self.session.add(
            DataTypeRow(
                **definition.model_dump(exclude={"definition", "registry"}),
                owner_id=owner,
                registry_kind=definition.registry,
                scope_id=definition.project_id or definition.workspace_id or owner,
                definition=definition.definition.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def list_types(
        self,
        organization_id: UUID,
        workspace_id: UUID | None,
        project_id: UUID | None,
        after: UUID | None,
    ) -> list[DataType]:
        query = select(DataTypeRow).where(
            or_(
                DataTypeRow.organization_id == organization_id,
                DataTypeRow.organization_id.is_(None),
            )
        )
        query = query.where(
            or_(DataTypeRow.workspace_id.is_(None), DataTypeRow.workspace_id == workspace_id)
        )
        query = query.where(
            or_(DataTypeRow.project_id.is_(None), DataTypeRow.project_id == project_id)
        )
        if after:
            query = query.where(DataTypeRow.id > after)
        return [
            type_contract(row)
            for row in self.session.scalars(query.order_by(DataTypeRow.id).limit(101))
        ]

    def record(self, organization_id: UUID | None, record_id: UUID) -> DataRecord | None:
        row = self.session.scalar(
            select(DataRecordRow)
            .where(DataRecordRow.organization_id == organization_id, DataRecordRow.id == record_id)
            .with_for_update()
        )
        return record_contract(row) if row else None

    def by_code(self, organization_id: UUID | None, type_id: UUID, code: str) -> DataRecord | None:
        row = self.session.scalar(
            select(DataRecordRow).where(
                DataRecordRow.organization_id == organization_id,
                DataRecordRow.type_id == type_id,
                DataRecordRow.code == code,
            )
        )
        return record_contract(row) if row else None

    def create_record(self, record: DataRecord) -> None:
        self.session.add(
            DataRecordRow(
                **record.model_dump(exclude={"values"}),
                owner_id=record.organization_id or GLOBAL_OWNER,
                values=record.values.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def update_record(self, record: DataRecord, expected_version: int) -> bool:
        result = self.session.execute(
            update(DataRecordRow)
            .where(
                DataRecordRow.organization_id == record.organization_id,
                DataRecordRow.id == record.id,
                DataRecordRow.version == expected_version,
            )
            .values(
                name=record.name,
                status=record.status,
                valid_from=record.valid_from,
                valid_until=record.valid_until,
                values=record.values.model_dump(mode="json"),
                version=record.version,
            )
        )
        return bool(result.rowcount == 1)  # type: ignore[attr-defined]

    def list_records(
        self, organization_id: UUID | None, type_id: UUID, after: UUID | None
    ) -> list[DataRecord]:
        query = select(DataRecordRow).where(
            DataRecordRow.organization_id == organization_id, DataRecordRow.type_id == type_id
        )
        if after:
            query = query.where(DataRecordRow.id > after)
        return [
            record_contract(row)
            for row in self.session.scalars(query.order_by(DataRecordRow.id).limit(101))
        ]
