"""Typed catalog contracts for immutable curated pack releases."""

from pydantic import Field

from operations.contracts import Command
from operations.modules.domain_packs.application.dependency_resolution import PackRelease


class RegistryIssue(Command):
    code: str
    locator: str | None = None
    message: str


class RegistrySnapshot(Command):
    valid: bool
    releases: list[PackRelease] = Field(default_factory=list)
    issues: list[RegistryIssue] = Field(default_factory=list)
