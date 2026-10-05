import hashlib
from datetime import date
from typing import Literal
from uuid import UUID, uuid7

from pydantic import ValidationError

from operations.contracts import ServiceError
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.master_data.application.contracts import (
    DataRecord,
    FieldKind,
    ImportIssue,
    ImportPreview,
    RecordStatus,
    RecordValues,
    TabularAdapter,
)
from operations.modules.master_data.application.service import MasterDataService


class MasterDataTransfer:
    def __init__(self, service: MasterDataService, tabular: TabularAdapter) -> None:
        self.service, self.tabular = service, tabular

    @staticmethod
    def literal(value: str, format: Literal["csv", "xlsx"]) -> str:
        if (
            format == "csv"
            and value.startswith("'")
            and (
                value[1:].lstrip().startswith(("=", "+", "-", "@"))
                or value[1:].startswith(("\t", "\r"))
            )
        ):
            return value[1:]
        return value

    def import_records(
        self,
        context: RequestContext,
        organization_id: UUID,
        type_id: UUID,
        data: bytes,
        format: Literal["csv", "xlsx"],
        dry_run: bool,
        expected_sha256: str | None,
        expected_type_version: int,
    ) -> ImportPreview:
        definition = self.service.definition(context, organization_id, type_id, True)
        if definition.version != expected_type_version:
            raise ServiceError(409, "version_conflict")
        digest = hashlib.sha256(data).hexdigest()
        if not dry_run and digest != expected_sha256:
            raise ServiceError(409, "import_preview_required")
        rows = self.tabular.parse(data, format)
        if len(rows) < 2:
            raise ServiceError(422, "empty_import")
        header = rows[0]
        base_headers = {"id", "code", "name", "status", "valid_from", "valid_until"}
        fields = {field.key: field for field in definition.definition.fields}
        if (
            len(set(header)) != len(header)
            or not {"code", "name"} <= set(header)
            or set(header) - base_headers - fields.keys()
        ):
            raise ServiceError(422, "invalid_import_headers")
        issues: list[ImportIssue] = []
        records: list[DataRecord] = []
        seen: set[str] = set()
        for number, cells in enumerate(rows[1:], start=2):
            if not any(cells):
                continue
            try:
                if len(cells) != len(header):
                    raise ServiceError(422, "import_column_count")
                values = dict(zip(header, cells, strict=True))
                code = values["code"]
                if code in seen or self.service.store.by_code(organization_id, type_id, code):
                    raise ServiceError(409, "duplicate_master_data_code")
                seen.add(code)
                dynamic: dict[str, str | int | bool | None] = {}
                for key, field in fields.items():
                    value = values.get(key, "")
                    if not value:
                        dynamic[key] = None
                    elif field.kind == FieldKind.INTEGER:
                        dynamic[key] = int(value)
                    elif field.kind == FieldKind.BOOLEAN:
                        if value not in {"true", "false"}:
                            raise ServiceError(422, "invalid_master_data_value")
                        dynamic[key] = value == "true"
                    else:
                        # Exported CSV text is spreadsheet-safe; recover its literal value.
                        dynamic[key] = self.literal(value, format)
                record = DataRecord(
                    id=uuid7(),
                    organization_id=organization_id,
                    type_id=type_id,
                    code=code,
                    name=self.literal(values["name"], format),
                    status=RecordStatus(values.get("status") or "active"),
                    valid_from=date.fromisoformat(values["valid_from"])
                    if values.get("valid_from")
                    else None,
                    valid_until=date.fromisoformat(values["valid_until"])
                    if values.get("valid_until")
                    else None,
                    values=RecordValues(fields=dynamic),
                )
                self.service.validate(definition, record)
                records.append(record)
            except ServiceError as error:
                issues.append(ImportIssue(row=number, code=error.code))
            except ValueError, ValidationError:
                issues.append(ImportIssue(row=number, code="invalid_master_data_value"))
        preview = ImportPreview(rows=records, issues=issues, source_sha256=digest)
        if dry_run:
            return preview
        if issues or not records:
            raise ServiceError(422, "import_validation_failed")
        for record in records:
            self.service.store.create_record(record)
            self.service.event(
                context, organization_id, "master_data.record.imported", record.id, record.version
            )
        self.service.event(
            context,
            organization_id,
            "master_data.import.completed",
            type_id,
            definition.version,
            digest,
        )
        return preview

    def export_records(
        self,
        context: RequestContext,
        organization_id: UUID,
        type_id: UUID,
        format: Literal["csv", "xlsx"],
        cursor: UUID | None,
    ) -> tuple[bytes, UUID | None]:
        definition = self.service.definition(context, organization_id, type_id)
        records = self.service.store.list_records(definition.organization_id, type_id, cursor)
        fields = [field.key for field in definition.definition.fields]
        rows = [["id", "code", "name", "status", "valid_from", "valid_until", *fields]]
        for record in records[:100]:
            dynamic = [record.values.fields.get(key) for key in fields]
            cells = [
                ""
                if value is None
                else (str(value).lower() if isinstance(value, bool) else str(value))
                for value in dynamic
            ]
            rows.append(
                [
                    str(record.id),
                    record.code,
                    record.name,
                    record.status,
                    record.valid_from.isoformat() if record.valid_from else "",
                    record.valid_until.isoformat() if record.valid_until else "",
                    *cells,
                ]
            )
        self.service.event(
            context, organization_id, "master_data.export.generated", type_id, definition.version
        )
        return self.tabular.export(rows, format), records[99].id if len(records) > 100 else None
