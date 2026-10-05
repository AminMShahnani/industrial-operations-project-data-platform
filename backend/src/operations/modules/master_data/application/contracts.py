from datetime import date
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from operations.contracts import Command


class DataScope(StrEnum):
    GLOBAL = "global"
    ORGANIZATION = "organization"
    WORKSPACE = "workspace"
    PROJECT = "project"


class RecordStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"


class FieldKind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    ENUM = "enum"
    REFERENCE = "reference"


class RegistryKind(StrEnum):
    CUSTOM = "custom"
    LOCATION = "location"
    ASSET = "asset"
    UNIT = "unit"
    CURRENCY = "currency"
    SHIFT = "shift"


class DataField(Command):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    kind: FieldKind
    required: bool = False
    choices: list[str] = Field(default_factory=list, max_length=100)
    reference_type_id: UUID | None = None

    @model_validator(mode="after")
    def coherent(self) -> DataField:
        if (self.kind == FieldKind.ENUM) != bool(self.choices):
            raise ValueError("Only enum fields require choices")
        if len(set(self.choices)) != len(self.choices) or any(
            len(item) > 120 for item in self.choices
        ):
            raise ValueError("Invalid enum choices")
        if (self.kind == FieldKind.REFERENCE) != (self.reference_type_id is not None):
            raise ValueError("Reference fields require a target type")
        return self


class DataSchema(Command):
    fields: list[DataField] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def unique_keys(self) -> DataSchema:
        if len({field.key for field in self.fields}) != len(self.fields):
            raise ValueError("Duplicate field keys")
        if {field.key for field in self.fields} & {
            "id",
            "code",
            "name",
            "status",
            "valid_from",
            "valid_until",
        }:
            raise ValueError("Field keys must not overlap built-in record columns")
        return self


class DataType(Command):
    id: UUID
    organization_id: UUID | None
    workspace_id: UUID | None
    project_id: UUID | None
    scope: DataScope
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
    name: str = Field(min_length=1, max_length=120)
    registry: RegistryKind
    definition: DataSchema
    active: bool = True
    version: int = 1


class RecordValues(Command):
    # Decimal, ISO date and UUID reference values use canonical text on the wire.
    fields: dict[str, StrictStr | StrictInt | StrictBool | None] = Field(
        default_factory=dict, max_length=50
    )


class DataRecord(Command):
    id: UUID
    organization_id: UUID | None
    type_id: UUID
    code: str
    name: str
    status: RecordStatus = RecordStatus.ACTIVE
    valid_from: date | None = None
    valid_until: date | None = None
    values: RecordValues = Field(default_factory=RecordValues)
    version: int = 1


class ImportIssue(Command):
    row: int
    code: str


class ImportPreview(Command):
    rows: list[DataRecord]
    issues: list[ImportIssue]
    source_sha256: str


class MasterDataReader(Protocol):
    def project_references(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None,
        location_ids: list[UUID],
        asset_ids: list[UUID],
    ) -> None: ...


class DataStore(Protocol):
    def type(self, organization_id: UUID | None, type_id: UUID) -> DataType | None: ...
    def create_type(self, definition: DataType) -> None: ...
    def list_types(
        self,
        organization_id: UUID,
        workspace_id: UUID | None,
        project_id: UUID | None,
        after: UUID | None,
    ) -> list[DataType]: ...
    def record(self, organization_id: UUID | None, record_id: UUID) -> DataRecord | None: ...
    def by_code(
        self, organization_id: UUID | None, type_id: UUID, code: str
    ) -> DataRecord | None: ...
    def create_record(self, record: DataRecord) -> None: ...
    def update_record(self, record: DataRecord, expected_version: int) -> bool: ...
    def list_records(
        self, organization_id: UUID | None, type_id: UUID, after: UUID | None
    ) -> list[DataRecord]: ...


class TabularAdapter(Protocol):
    def parse(self, data: bytes, format: Literal["csv", "xlsx"]) -> list[list[str]]: ...
    def export(self, rows: list[list[str]], format: Literal["csv", "xlsx"]) -> bytes: ...
