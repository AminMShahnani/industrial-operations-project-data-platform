from dataclasses import dataclass
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from operations.contracts import Command


class OrganizationSettings(Command):
    locale: str = Field(default="en", min_length=2, max_length=35, pattern=r"^[A-Za-z0-9-]+$")
    timezone: str = "UTC"
    unit_system: str = Field(default="SI", pattern="^(SI|US|custom)$")
    brand_name: str | None = Field(default=None, max_length=120)

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Unknown timezone") from error
        return value


@dataclass(frozen=True)
class Organization:
    id: UUID
    name: str
    settings: OrganizationSettings
    active: bool
    version: int


class OrganizationStore(Protocol):
    def get(self, organization_id: UUID) -> Organization | None: ...
    def create(self, organization: Organization) -> None: ...
    def update(self, organization: Organization, expected_version: int) -> bool: ...


class OrganizationReader(Protocol):
    def active(self, organization_id: UUID) -> Organization: ...
    def lock(self, organization_id: UUID) -> None: ...


class OrganizationLock(Protocol):
    def lock(self, organization_id: UUID) -> None: ...
