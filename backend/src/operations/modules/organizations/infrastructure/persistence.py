from uuid import UUID

from sqlalchemy import Boolean, Integer, String, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.organizations.application.contracts import (
    Organization,
    OrganizationSettings,
)
from operations.platform.database import Base


class OrganizationRow(Base):
    __tablename__ = "organizations"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    locale: Mapped[str] = mapped_column(String(35))
    timezone: Mapped[str] = mapped_column(String(80))
    unit_system: Mapped[str] = mapped_column(String(10))
    brand_name: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean)
    version: Mapped[int] = mapped_column(Integer)


class OrganizationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, organization_id: UUID) -> Organization | None:
        row = self.session.get(OrganizationRow, organization_id, with_for_update=True)
        if row is None:
            return None
        return Organization(
            row.id,
            row.name,
            OrganizationSettings(
                locale=row.locale,
                timezone=row.timezone,
                unit_system=row.unit_system,
                brand_name=row.brand_name,
            ),
            row.active,
            row.version,
        )

    def create(self, organization: Organization) -> None:
        self.session.add(
            OrganizationRow(
                id=organization.id,
                name=organization.name,
                active=organization.active,
                version=organization.version,
                **organization.settings.model_dump(),
            )
        )
        self.session.flush()

    def update(self, organization: Organization, expected_version: int) -> bool:
        result = self.session.execute(
            update(OrganizationRow)
            .where(
                OrganizationRow.id == organization.id,
                OrganizationRow.version == expected_version,
            )
            .values(
                name=organization.name,
                active=organization.active,
                version=organization.version,
                **organization.settings.model_dump(),
            )
        )
        return bool(result.rowcount == 1)  # type: ignore[attr-defined]
