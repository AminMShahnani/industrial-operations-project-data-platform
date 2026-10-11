"""Bounded, literal-safe tabular report export rendering."""

import csv
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from io import BytesIO, StringIO
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell


class TabularReportRenderer:
    def render(
        self,
        columns: Sequence[str],
        rows: Sequence[Sequence[str]],
        format: Literal["csv", "xlsx", "pdf"],
    ) -> bytes:
        matrix = [list(columns), *[list(row) for row in rows]]
        if format == "pdf":
            return self._pdf(matrix)
        if format == "csv":
            output = StringIO(newline="")
            writer = csv.writer(output, lineterminator="\r\n")
            for row in matrix:
                writer.writerow([self._safe_csv(value) for value in row])
            return output.getvalue().encode("utf-8-sig")

        workbook = Workbook(write_only=True)
        workbook.properties.created = datetime(2000, 1, 1, tzinfo=UTC)
        workbook.properties.modified = datetime(2000, 1, 1, tzinfo=UTC)
        sheet = workbook.create_sheet("Report")
        for row in matrix:
            cells = []
            for value in row:
                cell = WriteOnlyCell(sheet, value=value)
                cell.data_type = "s"
                cells.append(cell)
            sheet.append(cells)
        output_bytes = BytesIO()
        workbook.save(output_bytes)
        workbook.close()
        normalized = BytesIO()
        with (
            ZipFile(BytesIO(output_bytes.getvalue())) as source,
            ZipFile(normalized, "w", compression=ZIP_DEFLATED, compresslevel=9) as target,
        ):
            for name in sorted(source.namelist()):
                entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = ZIP_DEFLATED
                entry.external_attr = 0o600 << 16
                content = source.read(name)
                if name == "docProps/core.xml":
                    content = re.sub(
                        rb"(<dcterms:modified[^>]*>)[^<]+(</dcterms:modified>)",
                        rb"\g<1>2000-01-01T00:00:00Z\g<2>",
                        content,
                    )
                target.writestr(entry, content, compress_type=ZIP_DEFLATED, compresslevel=9)
        return normalized.getvalue()

    @staticmethod
    def _pdf(matrix: Sequence[Sequence[str]]) -> bytes:
        """Render a bounded text-only PDF (no HTML, scripts, fonts or external assets)."""
        text_rows = []
        for row in matrix:
            value = " | ".join(
                str(item)
                .replace("\r", " ")
                .replace("\n", " ")
                .replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
                for item in row
            )
            text_rows.append(value[:180])
        page_rows = [text_rows[index : index + 60] for index in range(0, len(text_rows), 60)] or [
            []
        ]
        page_refs = [4 + index * 2 for index in range(len(page_rows))]
        kids = " ".join(f"{identifier} 0 R" for identifier in page_refs)
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kids}] /Count {len(page_rows)} >>".encode(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
        ]
        for index, rows in enumerate(page_rows):
            page_number = 4 + index * 2
            content_number = page_number + 1
            page_object = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_number} 0 R >>"
            )
            objects.append(page_object.encode())
            commands = ["BT", "/F1 9 Tf", "40 800 Td", "12 TL"]
            for row_index, row in enumerate(rows):
                if row_index:
                    commands.append("T*")
                commands.append(f"({row}) Tj")
            commands.append("ET")
            stream = "\n".join(commands).encode("ascii", errors="replace")
            objects.append(
                b"<< /Length "
                + str(len(stream)).encode()
                + b" >>\nstream\n"
                + stream
                + b"\nendstream"
            )
        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, body in enumerate(objects, start=1):
            offsets.append(len(output))
            output.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
        xref = len(output)
        output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode())
        output.extend(
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        )
        return bytes(output)

    @staticmethod
    def _safe_csv(value: str) -> str:
        if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r")):
            return "'" + value
        return value
