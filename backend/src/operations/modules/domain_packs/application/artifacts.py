"""Typed, declarative pack artifacts and stable cross-artifact references."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid5

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from semantic_version import Version  # type: ignore[import-untyped]

from operations.contracts import Command
from operations.modules.forms.application.contracts import FormDefinition
from operations.modules.master_data.application.contracts import DataSchema, RegistryKind
from operations.modules.workflows.application.contracts import WorkflowDefinition

_REFERENCE_NAMESPACE = UUID("c4095c51-a215-48c2-aef2-6c2b60c03b4b")

type PackJsonValue = (
    None
    | StrictBool
    | StrictInt
    | float
    | StrictStr
    | list[PackJsonValue]
    | dict[str, PackJsonValue]
)
type PackJsonObject = dict[str, PackJsonValue]


class PackArtifactKind(StrEnum):
    FORM = "form"
    MASTER_DATA_TYPE = "master_data_type"
    WORKFLOW = "workflow"
    AUTOMATION_TEMPLATE = "automation_template"
    KPI = "kpi"
    MAPPING_PROFILE = "mapping_profile"


class PackArtifactReference(Command):
    """Exact immutable target; references never follow a floating version."""

    pack_id: str = Field(min_length=3, max_length=180, pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
    pack_version: str = Field(
        min_length=5,
        max_length=128,
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$",
    )
    kind: PackArtifactKind
    artifact_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
    version: int = Field(ge=1)

    @field_validator("pack_version")
    @classmethod
    def valid_pack_version(cls, value: str) -> str:
        Version(value, partial=False)
        return value

    def token(self) -> UUID:
        return uuid5(
            _REFERENCE_NAMESPACE,
            f"{self.pack_id}:{self.pack_version}:{self.kind.value}:"
            f"{self.artifact_id}:{self.version}",
        )


class PackArtifactEnvelope(Command):
    schema_version: Literal[1] = 1
    artifact_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
    artifact_version: int = Field(ge=1)
    kind: PackArtifactKind
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    # Raw JSON is confined to the package boundary. validate_artifact returns one
    # of the typed owning-module contracts before this content is used or imported.
    definition: PackJsonObject


class PackFormArtifact(Command):
    envelope: PackArtifactEnvelope
    definition: FormDefinition
    references: list[PackArtifactReference] = Field(max_length=100)


class PackMasterDataTypeDefinition(Command):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
    name: str = Field(min_length=1, max_length=120)
    registry: RegistryKind = RegistryKind.CUSTOM
    definition: DataSchema


class PackMasterDataTypeArtifact(Command):
    envelope: PackArtifactEnvelope
    definition: PackMasterDataTypeDefinition
    references: list[PackArtifactReference] = Field(max_length=100)


class PackWorkflowArtifact(Command):
    envelope: PackArtifactEnvelope
    definition: WorkflowDefinition
    references: list[PackArtifactReference] = Field(min_length=1, max_length=1)


class PackAutomationTemplateDefinition(Command):
    trigger: Literal["task.overdue", "submission.submitted"]
    action: Literal["notify_manager", "create_investigation_task"]
    source_form: UUID | None = None
    condition_field: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,59}$")
    condition_equals: str | None = Field(default=None, min_length=1, max_length=120)
    threshold_hours: int | None = Field(default=None, ge=1, le=720)

    @model_validator(mode="after")
    def coherent(self) -> PackAutomationTemplateDefinition:
        if self.trigger == "task.overdue":
            if self.source_form or self.condition_field or self.condition_equals:
                raise ValueError("overdue_template_cannot_reference_submission_fields")
            if self.threshold_hours is None:
                raise ValueError("overdue_template_requires_threshold")
        elif (self.condition_field is None) != (self.condition_equals is None):
            raise ValueError("automation_condition_requires_field_and_value")
        return self


class PackAutomationTemplateArtifact(Command):
    envelope: PackArtifactEnvelope
    definition: PackAutomationTemplateDefinition
    references: list[PackArtifactReference] = Field(default_factory=list, max_length=1)


class PackMappingField(Command):
    source_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    target_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    required: bool = False


class PackMappingProfileDefinition(Command):
    source_kind: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]*$")
    target_kind: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]*$")
    fields: list[PackMappingField] = Field(min_length=1, max_length=100)


class PackMappingProfileArtifact(Command):
    envelope: PackArtifactEnvelope
    definition: PackMappingProfileDefinition
    references: list[PackArtifactReference] = Field(default_factory=list, max_length=100)


class PackKpiDefinition(Command):
    metric: Literal["count", "sum", "average"]
    source_form: UUID
    source_field: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,59}$")
    unit: str = Field(min_length=1, max_length=40)
    time_field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    group_field: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,59}$")
    window_days: int = Field(ge=1, le=366)


class PackKpiArtifact(Command):
    envelope: PackArtifactEnvelope
    definition: PackKpiDefinition
    references: list[PackArtifactReference] = Field(min_length=1, max_length=1)


type ValidatedPackArtifact = (
    PackFormArtifact
    | PackMasterDataTypeArtifact
    | PackWorkflowArtifact
    | PackAutomationTemplateArtifact
    | PackMappingProfileArtifact
    | PackKpiArtifact
)


def _find_reference_values(value: object) -> list[PackArtifactReference]:
    found: list[PackArtifactReference] = []
    if isinstance(value, Mapping):
        if set(value) == {"$artifact_ref"}:
            found.append(PackArtifactReference.model_validate(value["$artifact_ref"]))
        else:
            for nested in value.values():
                found.extend(_find_reference_values(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_find_reference_values(nested))
    return found


def _resolve_reference_tokens(value: object) -> object:
    if isinstance(value, Mapping):
        if set(value) == {"$artifact_ref"}:
            return str(PackArtifactReference.model_validate(value["$artifact_ref"]).token())
        return {key: _resolve_reference_tokens(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_resolve_reference_tokens(nested) for nested in value]
    return value


def _assert_reference_slots(kind: PackArtifactKind, definition: object) -> None:
    """Permit references only in fields whose owning contracts define a typed link."""
    allowed_by_kind: dict[PackArtifactKind, set[tuple[str, ...]]] = {
        PackArtifactKind.FORM: {("sections", "*", "components", "*", "source", "type_id")},
        PackArtifactKind.MASTER_DATA_TYPE: {("definition", "fields", "*", "reference_type_id")},
        PackArtifactKind.WORKFLOW: {("form_id",)},
        PackArtifactKind.AUTOMATION_TEMPLATE: {("source_form",)},
        PackArtifactKind.KPI: {("source_form",)},
        PackArtifactKind.MAPPING_PROFILE: set(),
    }
    allowed = allowed_by_kind[kind]

    def visit(value: object, path: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            if set(value) == {"$artifact_ref"}:
                normalized = tuple("*" if part.isdecimal() else part for part in path)
                if normalized not in allowed:
                    raise ValueError("artifact_reference_in_unsupported_field")
                return
            for key, nested in value.items():
                if not isinstance(key, str):
                    raise ValueError("artifact_object_keys_must_be_strings")
                visit(nested, (*path, key))
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                visit(nested, (*path, str(index)))

    visit(definition, ())


def validate_artifact(document: object) -> ValidatedPackArtifact:
    """Validate the artifact envelope and owning-module schema without execution."""
    if not isinstance(document, dict):
        raise ValueError("artifact_document_must_be_object")
    envelope = PackArtifactEnvelope.model_validate(document)
    raw_definition = document.get("definition")
    if not isinstance(raw_definition, dict):
        raise ValueError("artifact_definition_must_be_object")
    _assert_reference_slots(envelope.kind, raw_definition)
    resolved_definition = _resolve_reference_tokens(raw_definition)
    if not isinstance(resolved_definition, dict):
        raise ValueError("artifact_definition_must_be_object")
    typed_definition = resolved_definition
    references = _find_reference_values(raw_definition)
    if envelope.kind == PackArtifactKind.FORM:
        parsed = FormDefinition.model_validate(typed_definition)
        from operations.modules.forms.application.runtime import compile_definition

        compile_definition(parsed)
        result: ValidatedPackArtifact = PackFormArtifact(
            envelope=envelope, definition=parsed, references=references
        )
    elif envelope.kind == PackArtifactKind.MASTER_DATA_TYPE:
        parsed_type = PackMasterDataTypeDefinition.model_validate(typed_definition)
        result = PackMasterDataTypeArtifact(
            envelope=envelope, definition=parsed_type, references=references
        )
    elif envelope.kind == PackArtifactKind.WORKFLOW:
        parsed_workflow = WorkflowDefinition.model_validate(typed_definition)
        result = PackWorkflowArtifact(
            envelope=envelope, definition=parsed_workflow, references=references
        )
    elif envelope.kind == PackArtifactKind.AUTOMATION_TEMPLATE:
        parsed_automation = PackAutomationTemplateDefinition.model_validate(typed_definition)
        if (parsed_automation.source_form is None) != (not references):
            raise ValueError("automation_source_form_reference_mismatch")
        result = PackAutomationTemplateArtifact(
            envelope=envelope, definition=parsed_automation, references=references
        )
    elif envelope.kind == PackArtifactKind.MAPPING_PROFILE:
        parsed_mapping = PackMappingProfileDefinition.model_validate(typed_definition)
        if len({field.source_key for field in parsed_mapping.fields}) != len(
            parsed_mapping.fields
        ) or len({field.target_key for field in parsed_mapping.fields}) != len(
            parsed_mapping.fields
        ):
            raise ValueError("mapping_profile_fields_must_be_unique")
        result = PackMappingProfileArtifact(
            envelope=envelope, definition=parsed_mapping, references=references
        )
    else:
        parsed_kpi = PackKpiDefinition.model_validate(typed_definition)
        if not any(parsed_kpi.source_form == reference.token() for reference in references):
            raise ValueError("kpi_source_form_reference_missing")
        result = PackKpiArtifact(envelope=envelope, definition=parsed_kpi, references=references)

    if result.envelope.kind != envelope.kind:
        raise ValueError("artifact_kind_mismatch")
    return result


def artifact_json_schema() -> dict[str, object]:
    """Return the strict schema for all supported artifact envelope variants."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "oneOf": [
            PackFormArtifact.model_json_schema(),
            PackMasterDataTypeArtifact.model_json_schema(),
            PackWorkflowArtifact.model_json_schema(),
            PackAutomationTemplateArtifact.model_json_schema(),
            PackKpiArtifact.model_json_schema(),
            PackMappingProfileArtifact.model_json_schema(),
        ],
    }
