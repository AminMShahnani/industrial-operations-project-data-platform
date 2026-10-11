"""Typed, versioned contracts for declarative Domain Pack manifests."""

import re
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StrictStr, field_validator, model_validator
from semantic_version import SimpleSpec, Version  # type: ignore[import-untyped]

from operations.contracts import Command

_PACK_ID = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


class PackType(StrEnum):
    INDUSTRY = "industry"
    FUNCTIONAL = "functional"
    ORGANIZATION_OVERLAY = "organization_overlay"


class PackCapability(StrEnum):
    FIELDS = "fields"
    COMPONENTS = "components"
    FORMS = "forms"
    MASTER_DATA = "master-data"
    WORKFLOWS = "workflows"
    AUTOMATIONS = "automations"
    DASHBOARDS = "dashboards"
    REPORTS = "reports"
    ROLES = "roles"
    INTEGRATIONS = "integrations"
    IMPORT_MAPPINGS = "import-mappings"
    LOCALIZATION = "locales"


def normalized_version_spec(value: str) -> str:
    """Accept the documented whitespace-separated ranges and normalize to SimpleSpec."""
    clauses = [part for part in value.replace(",", " ").split() if part]
    if not clauses:
        raise ValueError("Version range must contain at least one constraint")
    return ",".join(clauses)


class PackDependency(Command):
    id: Annotated[StrictStr, Field(min_length=1, max_length=180, pattern=_PACK_ID.pattern)]
    version_range: Annotated[
        StrictStr, Field(min_length=1, max_length=128, pattern=r"^[<>=!~^0-9A-Za-z.+,* -]+$")
    ]

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not _PACK_ID.fullmatch(value):
            raise ValueError("Dependency id must be a namespaced slug")
        return value

    @field_validator("version_range")
    @classmethod
    def valid_range(cls, value: str) -> str:
        try:
            SimpleSpec(normalized_version_spec(value))
        except ValueError as exc:
            raise ValueError("Dependency version range is invalid") from exc
        return value


class PackContentChecksum(Command):
    path: Annotated[
        StrictStr,
        Field(
            min_length=1,
            max_length=240,
            pattern=(
                r"^(?:[A-Za-z0-9_-][A-Za-z0-9._-]*/)*"
                r"[A-Za-z0-9_-][A-Za-z0-9._-]*\.(csv|json|md|txt|yaml|yml)$"
            ),
        ),
    ]
    sha256: Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        if "\\" in value or value.startswith("/") or ":" in value:
            raise ValueError("Content path must be a relative POSIX path")
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("Content path cannot contain empty or traversal segments")
        if any(part.startswith(".") for part in parts):
            raise ValueError("Hidden content paths are not allowed")
        suffix = parts[-1].rsplit(".", maxsplit=1)[-1].lower()
        if suffix not in {"csv", "json", "md", "txt", "yaml", "yml"}:
            raise ValueError("Content file type is not supported")
        return value


class PackManifest(Command):
    schema_version: Annotated[StrictStr, Field(pattern=r"^1$")]
    id: Annotated[StrictStr, Field(min_length=3, max_length=180, pattern=_PACK_ID.pattern)]
    name: Annotated[StrictStr, Field(min_length=1, max_length=120)]
    version: Annotated[
        StrictStr,
        Field(
            min_length=5,
            max_length=128,
            pattern=(
                r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
                r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
                r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
            ),
        ),
    ]
    pack_type: PackType
    core_version_range: Annotated[
        StrictStr, Field(min_length=1, max_length=128, pattern=r"^[<>=!~^0-9A-Za-z.+,* -]+$")
    ]
    dependencies: list[PackDependency] = Field(default_factory=list, max_length=64)
    capabilities: list[PackCapability] = Field(min_length=1, max_length=32)
    content_checksums: list[PackContentChecksum] = Field(min_length=1, max_length=1000)
    publisher: Annotated[StrictStr, Field(min_length=1, max_length=120)]

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not _PACK_ID.fullmatch(value):
            raise ValueError("Pack id must be a namespaced slug")
        return value

    @field_validator("version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        try:
            Version(value, partial=False)
        except ValueError as exc:
            raise ValueError("Pack version must be a complete semantic version") from exc
        return value

    @field_validator("core_version_range")
    @classmethod
    def valid_core_range(cls, value: str) -> str:
        try:
            SimpleSpec(normalized_version_spec(value))
        except ValueError as exc:
            raise ValueError("Core compatibility range is invalid") from exc
        return value

    @field_validator("publisher")
    @classmethod
    def valid_publisher(cls, value: str) -> str:
        if value != value.strip() or not value:
            raise ValueError("Publisher name cannot be blank or padded")
        return value

    @model_validator(mode="after")
    def coherent(self) -> PackManifest:
        dependency_ids = [dependency.id for dependency in self.dependencies]
        if len(set(dependency_ids)) != len(dependency_ids):
            raise ValueError("Pack dependencies must be unique")
        if self.id in dependency_ids:
            raise ValueError("A pack cannot depend on itself")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("Pack capabilities must be unique")
        paths = [item.path.casefold() for item in self.content_checksums]
        if len(set(paths)) != len(paths):
            raise ValueError("Pack content paths must be unique")
        if "pack.yaml" in paths or "pack.yml" in paths:
            raise ValueError("Manifest cannot list itself as content")
        return self

    def supports_core(self, core_version: str) -> bool:
        return Version(core_version) in SimpleSpec(normalized_version_spec(self.core_version_range))
