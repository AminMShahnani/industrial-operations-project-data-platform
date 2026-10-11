"""Tenant-scoped Domain Pack installation and immutable provenance storage."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.domain_packs.application.contracts import (
    InstallationState,
    PackInstallation,
    PackInstallationStore,
    PackRegistryProvider,
)
from operations.modules.domain_packs.application.dependency_resolution import PackRelease
from operations.modules.domain_packs.application.manifest import PackContentChecksum
from operations.platform.database import Base


class PackInstallationRow(Base):
    __tablename__ = "domain_pack_installations"
    __table_args__ = (
        ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        ForeignKeyConstraint(
            ["organization_id", "installed_by"], ["users.organization_id", "users.id"]
        ),
        UniqueConstraint("organization_id", "id", name="uq_domain_pack_installation_tenant"),
        UniqueConstraint("organization_id", "pack_id", name="uq_domain_pack_installation_id"),
        Index("ix_domain_pack_installations_org_state", "organization_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    pack_id: Mapped[str] = mapped_column(String(180))
    version: Mapped[str] = mapped_column(String(128))
    content_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    row_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    installed_by: Mapped[UUID]


class PackProvenanceRow(Base):
    __tablename__ = "domain_pack_provenance"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "installation_id"],
            ["domain_pack_installations.organization_id", "domain_pack_installations.id"],
        ),
        UniqueConstraint(
            "organization_id",
            "installation_id",
            "version",
            name="uq_domain_pack_provenance_release",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    installation_id: Mapped[UUID]
    pack_id: Mapped[str] = mapped_column(String(180))
    version: Mapped[str] = mapped_column(String(128))
    package_sha256: Mapped[str] = mapped_column(String(64))
    artifacts: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PackInstallationRepository(PackInstallationStore):
    def __init__(self, session: Session, registry: PackRegistryProvider) -> None:
        self.session = session
        self.registry = registry

    @staticmethod
    def _contract(row: PackInstallationRow) -> PackInstallation:
        return PackInstallation(
            id=row.id,
            organization_id=row.organization_id,
            pack_id=row.pack_id,
            version=row.version,
            content_sha256=row.content_sha256,
            state=InstallationState(row.state),
            row_version=row.row_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
            installed_by=row.installed_by,
        )

    def get(self, organization_id: UUID, pack_id: str) -> PackInstallation | None:
        row = self.session.scalar(
            select(PackInstallationRow)
            .where(
                PackInstallationRow.organization_id == organization_id,
                PackInstallationRow.pack_id == pack_id,
            )
            .with_for_update()
        )
        return self._contract(row) if row else None

    def installations(self, organization_id: UUID) -> list[PackInstallation]:
        rows = self.session.scalars(
            select(PackInstallationRow)
            .where(PackInstallationRow.organization_id == organization_id)
            .order_by(PackInstallationRow.pack_id)
        )
        return [self._contract(row) for row in rows]

    def create(self, installation: PackInstallation) -> None:
        self.session.add(PackInstallationRow(**installation.model_dump(mode="python")))
        self.session.flush()

    def update(self, installation: PackInstallation, expected_row_version: int) -> bool:
        result = self.session.execute(
            update(PackInstallationRow)
            .where(
                PackInstallationRow.organization_id == installation.organization_id,
                PackInstallationRow.id == installation.id,
                PackInstallationRow.row_version == expected_row_version,
            )
            .values(**installation.model_dump(exclude={"id", "organization_id", "created_at"}))
        )
        return bool(result.rowcount == 1)  # type: ignore[attr-defined]

    def add_provenance(
        self,
        organization_id: UUID,
        installation_id: UUID,
        pack_id: str,
        version: str,
        package_sha256: str,
        artifacts: list[PackContentChecksum],
    ) -> None:
        from datetime import UTC
        from uuid import uuid7

        self.session.add(
            PackProvenanceRow(
                id=uuid7(),
                organization_id=organization_id,
                installation_id=installation_id,
                pack_id=pack_id,
                version=version,
                package_sha256=package_sha256,
                artifacts=[item.model_dump(mode="json") for item in artifacts],
                created_at=datetime.now(UTC),
            )
        )
        self.session.flush()

    def has_materialized_artifacts(self, organization_id: UUID, pack_id: str) -> bool:
        # Phase 8 retains installation and provenance rows as operational evidence.
        # Until every materialized artifact has explicit ownership links, uninstall
        # cannot prove that data/history is safe to remove. Disable remains available.
        return (
            self.session.scalar(
                select(PackInstallationRow.id).where(
                    PackInstallationRow.organization_id == organization_id,
                    PackInstallationRow.pack_id == pack_id,
                )
            )
            is not None
        )

    def registry_release(self, pack_id: str, version: str) -> PackRelease | None:
        snapshot = self.registry.snapshot()
        return next(
            (
                release
                for release in snapshot.releases
                if release.manifest.id == pack_id and release.manifest.version == version
            ),
            None,
        )
