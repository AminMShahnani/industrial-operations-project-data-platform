"""Audited operator-only global reference publication; preview is the default."""

import argparse
import hashlib
from datetime import date
from pathlib import Path
from uuid import uuid7

from operations.composition import compose
from operations.contracts import Command
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.master_data.application.contracts import (
    DataRecord,
    DataSchema,
    DataScope,
    DataType,
    RecordStatus,
    RecordValues,
    RegistryKind,
)
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from pydantic import Field
from sqlalchemy.orm import Session


class ReferenceRecord(Command):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
    name: str = Field(min_length=1, max_length=120)
    status: RecordStatus = RecordStatus.ACTIVE
    valid_from: date | None = None
    valid_until: date | None = None
    values: RecordValues = Field(default_factory=RecordValues)


class ReferencePublication(Command):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
    name: str = Field(min_length=1, max_length=120)
    registry: RegistryKind = RegistryKind.CUSTOM
    definition: DataSchema = Field(default_factory=DataSchema)
    records: list[ReferenceRecord] = Field(max_length=1000)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    if args.file.stat().st_size > 4 * 1024 * 1024:
        raise SystemExit("Reference publication exceeds 4 MiB")
    content = args.file.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if args.apply and args.expected_sha256 != digest:
        raise SystemExit("Preview and supply the matching file SHA-256 before applying")
    publication = ReferencePublication.model_validate_json(content)
    settings = Settings()  # type: ignore[call-arg]
    if not settings.oidc_issuer:
        raise SystemExit("Configure the trusted operator issuer")
    principal = Principal(settings.oidc_issuer, args.subject)
    definition = DataType(
        id=uuid7(),
        organization_id=None,
        workspace_id=None,
        project_id=None,
        scope=DataScope.GLOBAL,
        code=publication.code,
        name=publication.name,
        registry=publication.registry,
        definition=publication.definition,
    )
    records = [
        DataRecord(id=uuid7(), organization_id=None, type_id=definition.id, **record.model_dump())
        for record in publication.records
    ]
    engine = create_database_engine(settings)
    try:
        with Session(engine) as session, session.begin():
            compose(session, principal).master_data.publish_global(
                RequestContext(principal, uuid7(), uuid7()),
                definition,
                records,
                args.reason,
                not args.apply,
            )
    finally:
        engine.dispose()
    print(
        f"{'Published' if args.apply else 'Validated preview'}: {len(records)} records; "
        f"SHA-256 {digest}"
    )
    if args.apply:
        print(f"Type ID: {definition.id}")


if __name__ == "__main__":
    main()
