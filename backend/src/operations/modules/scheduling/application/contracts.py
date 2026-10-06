from datetime import datetime, time
from typing import Literal, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from operations.contracts import Command
from operations.modules.scheduling.domain.recurrence import local_instant, parse_rule


class Assignment(Command):
    kind: Literal["user", "team", "department", "role", "shift"]
    target_id: UUID | None = None
    role: (
        Literal[
            "Contributor", "ProjectManager", "WorkspaceAdmin", "WorkspaceOwner", "OrganizationAdmin"
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def target(self) -> Assignment:
        if (self.kind == "role") != (self.role is not None) or (self.kind != "role") != (
            self.target_id is not None
        ):
            raise ValueError("Exactly one typed assignment target required")
        return self

    def key(self) -> str:
        return self.kind + ":" + str(self.target_id or self.role)


class Recurrence(Command):
    kind: Literal[
        "one_time",
        "interval",
        "daily",
        "weekly",
        "monthly",
        "rrule",
        "shift",
        "milestone",
        "relative_event",
    ]
    timezone: str = Field(default="UTC", max_length=80)
    starts_local: datetime | None = None
    at: datetime | None = None
    interval_seconds: int | None = Field(default=None, ge=3600, le=31536000)
    rule: str | None = Field(default=None, max_length=300)
    shift_id: UUID | None = None
    milestone_id: UUID | None = None
    event_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_.]{0,59}$")
    offset_seconds: int = Field(default=0, ge=-2592000, le=2592000)

    @model_validator(mode="after")
    def coherent(self) -> Recurrence:
        allowed = {
            "one_time": {"at"},
            "interval": {"at", "interval_seconds"},
            "daily": {"starts_local"},
            "weekly": {"starts_local"},
            "monthly": {"starts_local"},
            "rrule": {"starts_local", "rule"},
            "shift": {"starts_local", "rule", "shift_id"},
            "milestone": {"milestone_id"},
            "relative_event": {"event_code"},
        }[self.kind]
        for name in {
            "at",
            "interval_seconds",
            "starts_local",
            "rule",
            "shift_id",
            "milestone_id",
            "event_code",
        }:
            if name not in allowed and getattr(self, name) is not None:
                raise ValueError("Recurrence property does not apply to its kind")
        if self.kind not in {"milestone", "relative_event"} and self.offset_seconds:
            raise ValueError("Offset requires an event or milestone")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown timezone") from error
        if self.kind in {"one_time", "interval"}:
            if self.at is None or self.at.tzinfo is None:
                raise ValueError("Aware anchor required")
            if self.kind == "interval" and self.interval_seconds is None:
                raise ValueError("Interval required")
        if self.kind in {"daily", "weekly", "monthly", "rrule", "shift"}:
            if self.starts_local is None or local_instant(self.starts_local, self.timezone) is None:
                raise ValueError("Valid naive local anchor required")
            parse_rule(
                self.rule or "FREQ=" + ("DAILY" if self.kind == "shift" else self.kind.upper())
            )
        if self.kind == "shift" and self.shift_id is None:
            raise ValueError("Pinned shift required")
        if self.kind == "milestone" and self.milestone_id is None:
            raise ValueError("Milestone required")
        if self.kind == "relative_event" and self.event_code is None:
            raise ValueError("Event code required")
        return self


class ScheduleDefinition(Command):
    form_id: UUID
    form_number: int = Field(ge=1)
    recurrence: Recurrence
    assignments: list[Assignment] = Field(min_length=1, max_length=30)
    due_after_seconds: int = Field(default=28800, ge=0, le=2592000)
    reminder_offsets: list[int] = Field(default_factory=lambda: [0, 86400], max_length=10)

    @model_validator(mode="after")
    def unique(self) -> ScheduleDefinition:
        if len({item.key() for item in self.assignments}) != len(self.assignments):
            raise ValueError("Duplicate assignment")
        if len(set(self.reminder_offsets)) != len(self.reminder_offsets) or any(
            abs(x) > 2592000 for x in self.reminder_offsets
        ):
            raise ValueError("Invalid reminders")
        return self


class Schedule(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    active_number: int | None = None
    revision: int = 1


class ScheduleVersion(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    schedule_id: UUID
    number: int = Field(ge=1)
    definition: ScheduleDefinition
    state: Literal["draft", "active", "paused", "retired"] = "draft"
    revision: int = 1
    form_version_id: UUID | None = None
    activated_at: datetime | None = None
    content_sha256: str | None = None


class Shift(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None = None
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    number: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    timezone: str = Field(max_length=80)
    starts_at: time
    duration_seconds: int = Field(ge=3600, le=86400)
    user_ids: list[UUID] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid(self) -> Shift:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown timezone") from error
        if self.starts_at.tzinfo or len(set(self.user_ids)) != len(self.user_ids):
            raise ValueError("Invalid shift roster/time")
        return self


class Trigger(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None = None
    code: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,59}$")
    occurred_at: datetime

    @model_validator(mode="after")
    def aware(self) -> Trigger:
        if self.occurred_at.tzinfo is None:
            raise ValueError("Aware event timestamp required")
        return self


class ScheduleStore(Protocol):
    def create(self, row: Schedule) -> None: ...
    def get(self, org: UUID, workspace: UUID, identifier: UUID) -> Schedule | None: ...
    def update(self, row: Schedule, expected: int) -> bool: ...
    def list_schedules(
        self, org: UUID, workspace: UUID, project: UUID | None, after: UUID | None
    ) -> list[Schedule]: ...
    def add_version(self, row: ScheduleVersion) -> None: ...
    def version(self, org: UUID, schedule: UUID, number: int) -> ScheduleVersion | None: ...
    def versions(self, org: UUID, schedule: UUID, after: UUID | None) -> list[ScheduleVersion]: ...
    def save_version(self, row: ScheduleVersion, expected: int) -> bool: ...
    def add_shift(self, row: Shift) -> None: ...
    def shift(self, org: UUID, workspace: UUID, identifier: UUID) -> Shift | None: ...
    def shifts(
        self, org: UUID, workspace: UUID, project: UUID | None, after: UUID | None
    ) -> list[Shift]: ...
    def add_trigger(self, row: Trigger) -> bool: ...
    def triggers(
        self,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        code: str,
        start: datetime,
        end: datetime,
    ) -> list[Trigger]: ...
