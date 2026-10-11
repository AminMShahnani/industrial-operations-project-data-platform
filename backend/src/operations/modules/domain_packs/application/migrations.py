"""Review-only, typed Domain Pack migration descriptors; these are never executed."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StrictStr, model_validator

from operations.contracts import Command


class MigrationArtifactKind(StrEnum):
    FORM = "form"
    WORKFLOW = "workflow"
    MASTER_DATA_TYPE = "master_data_type"
    REPORT = "report"
    DASHBOARD = "dashboard"
    AUTOMATION = "automation"


class MigrationFieldType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"


_STABLE_ID = r"^[a-z][a-z0-9_.-]{1,119}$"


class DeprecateArtifact(Command):
    operation: Literal["deprecate_artifact"]
    artifact_kind: MigrationArtifactKind
    artifact_id: StrictStr = Field(min_length=2, max_length=120, pattern=_STABLE_ID)
    reason: StrictStr = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def bounded_reason(self) -> DeprecateArtifact:
        if self.reason != self.reason.strip():
            raise ValueError("Migration reason cannot have surrounding whitespace")
        return self


class AddOptionalField(Command):
    operation: Literal["add_optional_field"]
    artifact_kind: Literal[MigrationArtifactKind.FORM, MigrationArtifactKind.MASTER_DATA_TYPE]
    artifact_id: StrictStr = Field(min_length=2, max_length=120, pattern=_STABLE_ID)
    field_id: StrictStr = Field(min_length=2, max_length=80, pattern=_STABLE_ID)
    field_type: MigrationFieldType
    label: StrictStr = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def bounded_label(self) -> AddOptionalField:
        if self.label != self.label.strip():
            raise ValueError("Field label cannot have surrounding whitespace")
        return self


MigrationOperation = Annotated[
    DeprecateArtifact | AddOptionalField,
    Field(discriminator="operation"),
]


class PackMigrationFile(Command):
    schema_version: Literal[1]
    operations: list[MigrationOperation] = Field(min_length=1, max_length=256)
