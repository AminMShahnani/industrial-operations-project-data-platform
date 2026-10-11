"""Typed reporting dataset and saved definition contracts."""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from operations.contracts import Command
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.tasks.application.contracts import TaskState


class OverdueTaskRow(Command):
    id: UUID | None
    project_id: UUID | None
    kind: Literal["form", "generic"] | None
    name: str | None
    state: TaskState | None
    due_at: AwareDatetime | None


class TaskStateGroup(Command):
    state: TaskState
    count: int = Field(ge=1)


class DueWeekGroup(Command):
    week_start: date | None
    label: str = Field(min_length=1, max_length=40)
    count: int = Field(ge=0)


class KpiAggregateGroup(Command):
    group: str | None
    value: float


class KpiAggregateResult(Command):
    unit: str = Field(min_length=1, max_length=40)
    start_date: date
    end_date: date
    groups: list[KpiAggregateGroup] = Field(max_length=100)


class OverdueTaskPage(Command):
    items: list[OverdueTaskRow] = Field(max_length=100)
    next_cursor: UUID | None
    groups: list[TaskStateGroup] = Field(max_length=9)
    due_week_groups: list[DueWeekGroup] = Field(max_length=13)
    kpi_result: KpiAggregateResult | None = None


class StateFilter(Command):
    field: Literal["state"]
    operator: Literal["eq"] = "eq"
    value: TaskState


class KindFilter(Command):
    field: Literal["kind"]
    operator: Literal["eq"] = "eq"
    value: Literal["form", "generic"]


class NameFilter(Command):
    field: Literal["name"]
    operator: Literal["contains"]
    value: str = Field(min_length=1, max_length=120)


class DueAtFilter(Command):
    field: Literal["due_at"]
    operator: Literal["before", "after"]
    value: AwareDatetime


class ProjectFilter(Command):
    field: Literal["project_id"]
    operator: Literal["eq"] = "eq"
    value: UUID


OverdueFilter = Annotated[
    StateFilter | KindFilter | NameFilter | DueAtFilter | ProjectFilter,
    Field(discriminator="field"),
]


class SavedKpiDefinition(Command):
    metric: Literal["count", "sum", "average"]
    source_form: UUID
    source_form_number: int = Field(default=1, ge=1)
    source_field: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,59}$")
    unit: str = Field(min_length=1, max_length=40)
    time_field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    group_field: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,59}$")
    window_days: int = Field(ge=1, le=366)


class SavedReportDefinition(Command):
    dataset: Literal["overdue_tasks", "pack_form_kpi"]
    scope: Literal["personal", "aggregate"] = "personal"
    columns: list[Literal["id", "project_id", "kind", "name", "state", "due_at"]] = Field(
        default_factory=list, max_length=6
    )
    filters: list[OverdueFilter] = Field(default_factory=list, max_length=10)
    sort_by: Literal["id"] = "id"
    sort_direction: Literal["asc", "desc"] = "asc"
    group_by: Literal["none", "state", "due_week"] = "none"
    kpi: SavedKpiDefinition | None = None

    @model_validator(mode="after")
    def coherent(self) -> SavedReportDefinition:
        if self.dataset == "pack_form_kpi":
            if (
                self.kpi is None
                or self.scope != "aggregate"
                or self.columns
                or self.filters
                or self.group_by != "none"
            ):
                raise ValueError("invalid_pack_kpi_report_definition")
            return self
        if self.kpi is not None or not self.columns:
            raise ValueError("invalid_overdue_report_definition")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("duplicate_report_column")
        if self.group_by == "state" and self.columns != ["state"]:
            raise ValueError("state_group_requires_state_column")
        if self.group_by == "state" and self.sort_direction != "asc":
            raise ValueError("state_group_sort_is_fixed")
        if self.group_by == "due_week" and self.columns != ["due_at"]:
            raise ValueError("due_week_group_requires_due_at_column")
        if self.group_by == "due_week" and self.sort_direction != "asc":
            raise ValueError("due_week_group_sort_is_fixed")
        return self


class SavedReportWrite(Command):
    name: str = Field(min_length=1, max_length=120)
    definition: SavedReportDefinition
    expected_version: int | None = Field(default=None, ge=1)


class SavedReport(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    owner_id: UUID
    name: str
    definition: SavedReportDefinition
    version: int
    definition_sha256: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    archived: bool = False
    audit_id: UUID


class SavedReportPage(Command):
    items: list[SavedReport] = Field(max_length=100)
    next_cursor: UUID | None


class ReportExport(Command):
    file_name: str
    media_type: str
    content: bytes


class ReportRenderer(Protocol):
    def render(
        self,
        columns: Sequence[str],
        rows: Sequence[Sequence[str]],
        format: Literal["csv", "xlsx", "pdf"],
    ) -> bytes: ...


class ReportExportJob(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    owner_id: UUID
    report_id: UUID
    report_version: int
    report_digest: str
    scope: Literal["personal", "aggregate"]
    format: Literal["csv", "xlsx", "pdf"]
    state: Literal["pending", "running", "completed", "failed", "expired", "revoked"]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    expires_at: AwareDatetime
    artifact_key: str | None = Field(default=None, exclude=True)
    artifact_sha256: str | None = Field(default=None, exclude=True)
    artifact_size: int | None = Field(default=None, ge=0, le=50_000_000, exclude=True)
    error_code: str | None = None


class ReportExportJobStore(Protocol):
    def create(self, job: ReportExportJob, definition: dict[str, object]) -> None: ...
    def get(
        self, organization_id: UUID, job_id: UUID, lock: bool = False
    ) -> ReportExportJob | None: ...
    def page(
        self, organization_id: UUID, workspace_id: UUID, owner_id: UUID
    ) -> list[ReportExportJob]: ...
    def save(self, job: ReportExportJob, expected_state: str) -> bool: ...
    def claim(
        self, organization_id: UUID, job_id: UUID, now: datetime
    ) -> ReportExportJob | None: ...
    def definition(self, organization_id: UUID, job_id: UUID) -> dict[str, object] | None: ...
    def due(self, now: datetime) -> list[tuple[UUID, UUID]]: ...
    def expired_artifacts(self, now: datetime) -> list[tuple[UUID, UUID, str]]: ...
    def expire(self, organization_id: UUID, job_id: UUID, now: datetime) -> bool: ...
    def expire_due(self, now: datetime) -> list[ReportExportJob]: ...


class SavedReportStore(Protocol):
    def create(self, report: SavedReport) -> None: ...
    def get(self, organization_id: UUID, report_id: UUID) -> SavedReport | None: ...
    def page(
        self, organization_id: UUID, workspace_id: UUID, owner_id: UUID, cursor: UUID | None
    ) -> list[SavedReport]: ...
    def append(self, report: SavedReport, expected_version: int) -> bool: ...
    def archive(
        self,
        organization_id: UUID,
        report_id: UUID,
        owner_id: UUID,
        expected: int,
        updated_at: datetime,
        audit_id: UUID,
    ) -> bool: ...


class DashboardWidgetDefinition(Command):
    report_id: UUID
    kind: Literal["table", "overdue_list", "status_distribution", "bar", "metric", "trend", "line"]
    title: str = Field(min_length=1, max_length=80)


class DashboardDefinition(Command):
    widgets: list[DashboardWidgetDefinition] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique_reports(self) -> DashboardDefinition:
        if len({widget.report_id for widget in self.widgets}) != len(self.widgets):
            raise ValueError("duplicate_dashboard_report")
        return self


class DashboardWrite(Command):
    name: str = Field(min_length=1, max_length=120)
    definition: DashboardDefinition
    expected_version: int | None = Field(default=None, ge=1)


class Dashboard(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    owner_id: UUID
    name: str
    definition: DashboardDefinition
    version: int
    definition_sha256: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    archived: bool = False
    audit_id: UUID


class DashboardPage(Command):
    items: list[Dashboard] = Field(max_length=100)
    next_cursor: UUID | None


class DashboardWidgetResult(Command):
    title: str
    kind: Literal["table", "overdue_list", "status_distribution", "bar", "metric", "trend", "line"]
    report: OverdueTaskPage
    metric_value: int | float | None = None


class DashboardResult(Command):
    dashboard_id: UUID
    version: int
    widgets: list[DashboardWidgetResult] = Field(max_length=6)


class DashboardStore(Protocol):
    def create(self, dashboard: Dashboard) -> None: ...
    def get(self, organization_id: UUID, dashboard_id: UUID) -> Dashboard | None: ...
    def page(
        self, organization_id: UUID, workspace_id: UUID, owner_id: UUID, cursor: UUID | None
    ) -> list[Dashboard]: ...
    def append(self, dashboard: Dashboard, expected_version: int) -> bool: ...
    def archive(
        self,
        organization_id: UUID,
        dashboard_id: UUID,
        owner_id: UUID,
        expected: int,
        updated_at: datetime,
        audit_id: UUID,
    ) -> bool: ...


class ReportWorkspaceReader(Protocol):
    def active(self, organization_id: UUID, workspace_id: UUID) -> object: ...


class ReportProjectReader(Protocol):
    def require_access(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        permission: str,
    ) -> object: ...
