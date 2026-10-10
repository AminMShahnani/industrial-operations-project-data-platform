"""Auditable, immutable integration endpoint administration contracts."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from operations.contracts import Command


class EndpointVersion(Command):
    audit_id: UUID
    endpoint_id: UUID
    organization_id: UUID
    workspace_id: UUID | None
    project_id: UUID | None
    version: int = Field(ge=1)
    signing_key_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=9, max_length=2048)
    secret_reference: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_/:.-]+$")
    state: Literal["active", "revoked"] = "active"
    created_by_id: UUID
    created_at: datetime

    @model_validator(mode="after")
    def scope_is_coherent(self) -> EndpointVersion:
        if self.project_id is not None and self.workspace_id is None:
            raise ValueError("webhook_endpoint_project_requires_workspace")
        if self.created_at.utcoffset() is None:
            raise ValueError("webhook_endpoint_timestamp_requires_timezone")
        return self


class EndpointCreate(Command):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=9, max_length=2048)
    secret_reference: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_/:.-]+$")
    signing_key_version: int = Field(ge=1)

    @model_validator(mode="after")
    def nonempty_name(self) -> EndpointCreate:
        if not self.name.strip():
            raise ValueError("webhook_endpoint_name_required")
        return self


class EndpointRevise(EndpointCreate):
    expected_version: int = Field(ge=1)


class EndpointRevoke(Command):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class EndpointView(Command):
    endpoint_id: UUID
    organization_id: UUID
    workspace_id: UUID | None
    project_id: UUID | None
    version: int = Field(ge=1)
    signing_key_version: int = Field(ge=1)
    name: str
    url: str
    state: Literal["active", "revoked"]
    secret_reference_present: Literal[True] = True
    created_at: datetime

    @classmethod
    def from_version(cls, row: EndpointVersion) -> EndpointView:
        return cls(
            endpoint_id=row.endpoint_id,
            organization_id=row.organization_id,
            workspace_id=row.workspace_id,
            project_id=row.project_id,
            version=row.version,
            signing_key_version=row.signing_key_version,
            name=row.name,
            url=row.url,
            state=row.state,
            created_at=row.created_at,
        )


class EndpointStore(Protocol):
    def add(self, row: EndpointVersion) -> None: ...
    def latest(self, organization_id: UUID, endpoint_id: UUID) -> EndpointVersion | None: ...
    def version(
        self, organization_id: UUID, endpoint_id: UUID, number: int
    ) -> EndpointVersion | None: ...
    def page(
        self,
        organization_id: UUID,
        workspace_id: UUID | None,
        project_id: UUID | None,
        after: UUID | None,
    ) -> list[EndpointVersion]: ...
