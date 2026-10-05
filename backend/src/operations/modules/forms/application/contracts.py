from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from operations.contracts import Command
from operations.modules.forms.domain.expressions import Node


class Expression(Command):
    op: Literal[
        "literal",
        "field",
        "context",
        "add",
        "subtract",
        "multiply",
        "divide",
        "eq",
        "ne",
        "lt",
        "lte",
        "gt",
        "gte",
        "and",
        "or",
        "not",
        "if",
        "coalesce",
        "concat",
        "length",
        "round",
    ]
    value: StrictStr | StrictInt | StrictBool | None = None
    key: str | None = Field(default=None, max_length=60)
    args: list[Expression] = Field(default_factory=list, max_length=20)

    def node(self) -> Node:
        return Node(self.op, self.value, self.key, tuple(arg.node() for arg in self.args))


type Kind = Literal[
    "text",
    "textarea",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "time",
    "select",
    "multi_select",
    "radio",
    "user",
    "department",
    "project",
    "master_data",
    "file",
    "image",
    "signature",
    "calculated",
    "table",
    "repeating_group",
    "display",
]


class Validation(Command):
    min_length: int | None = Field(default=None, ge=0, le=2000)
    max_length: int = Field(default=2000, ge=1, le=2000)
    minimum: str | None = Field(default=None, pattern=r"^-?[0-9]{1,18}(\.[0-9]{1,6})?$")
    maximum: str | None = Field(default=None, pattern=r"^-?[0-9]{1,18}(\.[0-9]{1,6})?$")
    max_rows: int = Field(default=100, ge=1, le=100)
    condition: Expression | None = None


class FieldPermissions(Command):
    read: Literal["all", "owner", "manager"] = "all"
    write: Literal["all", "owner", "manager"] = "all"


class DataSource(Command):
    type_id: UUID | None = None
    record_id: UUID | None = None
    previous_approved_key: str | None = Field(default=None, max_length=60)


class Presentation(Command):
    help_text: str = Field(default="", max_length=2000)
    placeholder: str = Field(default="", max_length=120)
    width: Literal["full", "half"] = "full"


class Component(Command):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    kind: Kind
    label: str = Field(min_length=1, max_length=120)
    required: bool = False
    validation: Validation = Field(default_factory=Validation)
    permissions: FieldPermissions = Field(default_factory=FieldPermissions)
    presentation: Presentation = Field(default_factory=Presentation)
    choices: list[str] = Field(default_factory=list, max_length=100)
    default: Expression | None = None
    visible_when: Expression | None = None
    required_when: Expression | None = None
    formula: Expression | None = None
    source: DataSource | None = None
    children: list[Component] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def coherent(self) -> Component:
        if (
            self.validation.min_length is not None
            and self.validation.min_length > self.validation.max_length
        ):
            raise ValueError("Invalid length interval")
        if (
            self.validation.minimum is not None
            and self.validation.maximum is not None
            and Decimal(self.validation.minimum) > Decimal(self.validation.maximum)
        ):
            raise ValueError("Invalid numeric interval")
        if (
            self.source
            and self.source.record_id
            and (self.kind != "master_data" or self.source.type_id is None)
        ):
            raise ValueError("Record defaults require an exact master-data type")
        if (
            self.source
            and self.source.previous_approved_key
            and (self.source.record_id or self.source.type_id)
        ):
            raise ValueError("Choose exactly one governed default source")
        if self.kind in {"select", "multi_select", "radio"}:
            if not self.choices or len(set(self.choices)) != len(self.choices):
                raise ValueError("Unique choices required")
            if any(not value or len(value) > 120 for value in self.choices):
                raise ValueError("Invalid choice")
        elif self.choices:
            raise ValueError("Choices apply only to selection components")
        if (self.kind == "calculated") != (self.formula is not None):
            raise ValueError("Calculated component requires a formula")
        if self.kind in {"table", "repeating_group"}:
            if not self.children or any(child.children for child in self.children):
                raise ValueError("Exactly one bounded repeating level is supported")
        elif self.children:
            raise ValueError("Children require a repeating component")
        if self.kind == "master_data" and (self.source is None or self.source.type_id is None):
            raise ValueError("Master lookup requires an exact type")
        return self


class LibraryPin(Command):
    artifact_id: UUID
    version: int = Field(ge=1)


class Section(Command):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    label: str = Field(min_length=1, max_length=120)
    components: list[Component] = Field(default_factory=list, max_length=100)
    references: list[LibraryPin] = Field(default_factory=list, max_length=30)


class FormDefinition(Command):
    schema_version: Literal[1] = 1
    sections: list[Section] = Field(min_length=1, max_length=30)


class Form(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None = None
    name: str
    version: int = 1


class FormVersion(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    form_id: UUID
    number: int
    state: Literal["draft", "published", "deprecated", "retired"] = "draft"
    definition: FormDefinition
    revision: int = 1
    published_at: datetime | None = None
    content_sha256: str | None = None


class LibraryArtifact(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
    version: int = Field(ge=1)
    kind: Literal["field", "component", "form"]
    definition: FormDefinition


type Text = Annotated[StrictStr, Field(max_length=2000)]
type Cell = Text | StrictInt | StrictBool | None
type Selection = Annotated[list[Text], Field(max_length=100)]
type Row = Annotated[dict[str, Cell | Selection], Field(max_length=30)]
type Value = Cell | Selection | Annotated[list[Row], Field(max_length=100)]


class FormValues(Command):
    fields: dict[str, Value] = Field(default_factory=dict, max_length=100)


class RuntimeIssue(Command):
    key: str
    code: str


class RuntimeResult(Command):
    values: FormValues
    visible_keys: list[str]
    required_keys: list[str]
    issues: list[RuntimeIssue]


class FormStore(Protocol):
    def create(self, form: Form) -> None: ...
    def get(self, organization_id: UUID, workspace_id: UUID, form_id: UUID) -> Form | None: ...
    def list_forms(
        self, organization_id: UUID, workspace_id: UUID, project_id: UUID | None, after: UUID | None
    ) -> list[Form]: ...
    def add_version(self, version: FormVersion) -> None: ...
    def version(self, organization_id: UUID, form_id: UUID, number: int) -> FormVersion | None: ...
    def versions(
        self, organization_id: UUID, form_id: UUID, after: UUID | None
    ) -> list[FormVersion]: ...
    def save_version(self, version: FormVersion, expected_revision: int) -> bool: ...
    def add_artifact(self, artifact: LibraryArtifact) -> None: ...
    def artifact(
        self, organization_id: UUID, workspace_id: UUID, pin: LibraryPin
    ) -> LibraryArtifact | None: ...
    def artifacts(
        self, organization_id: UUID, workspace_id: UUID, after: UUID | None
    ) -> list[LibraryArtifact]: ...


class LookupItem(Command):
    id: UUID
    label: str


class LookupPage(Command):
    items: list[LookupItem]
    next_cursor: UUID | None = None


class DefaultContext(Protocol):
    """Trusted application port. Future scheduling/workflow modules own the data."""

    def shift(
        self, organization_id: UUID, workspace_id: UUID, project_id: UUID | None, user_id: UUID
    ) -> str | None: ...
    def previous_approved(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        form_id: UUID,
        owner_id: UUID,
        field_key: str,
    ) -> Cell: ...
