"""Permission-scoped reporting datasets and saved report operations."""

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.files.application.contracts import PrivateStorage
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.iam.application.service import Authorization
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.reporting.application.contracts import (
    Dashboard,
    DashboardDefinition,
    DashboardPage,
    DashboardResult,
    DashboardStore,
    DashboardWidgetResult,
    DashboardWrite,
    DueWeekGroup,
    OverdueFilter,
    OverdueTaskPage,
    OverdueTaskRow,
    ReportExport,
    ReportExportJob,
    ReportExportJobStore,
    ReportProjectReader,
    ReportRenderer,
    ReportWorkspaceReader,
    SavedReport,
    SavedReportDefinition,
    SavedReportPage,
    SavedReportStore,
    SavedReportWrite,
    TaskStateGroup,
)
from operations.modules.tasks.application.contracts import TaskQueryFilter
from operations.modules.tasks.application.service import TaskService


class ReportingService:
    def __init__(
        self,
        tasks: TaskService,
        reports: SavedReportStore,
        dashboards: DashboardStore,
        renderer: ReportRenderer,
        authorization: Authorization,
        workspaces: ReportWorkspaceReader,
        projects: ReportProjectReader,
        audit: AuditWriter,
        export_jobs: ReportExportJobStore | None = None,
    ) -> None:
        self.tasks, self.reports, self.dashboards, self.renderer = (
            tasks,
            reports,
            dashboards,
            renderer,
        )
        self.authorization, self.workspaces, self.projects, self.audit = (
            authorization,
            workspaces,
            projects,
            audit,
        )
        self.export_jobs = export_jobs

    @staticmethod
    def _scope(organization_id: UUID, workspace_id: UUID) -> Scope:
        return Scope(organization_id, ScopeType.WORKSPACE, workspace_id)

    def _actor(self, actor: RequestContext, organization_id: UUID) -> UUID:
        return self.authorization.user(actor, organization_id).id

    def _access(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None,
    ) -> None:
        self.workspaces.active(organization_id, workspace_id)
        if project_id is None:
            self.authorization.require(
                actor, "workspace.read", self._scope(organization_id, workspace_id)
            )
        else:
            self.projects.require_access(
                actor, organization_id, workspace_id, project_id, "project.read"
            )

    def _read(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None,
        scope: Literal["personal", "aggregate"],
        cursor: UUID | None,
        filters: list[OverdueFilter] | None = None,
        columns: Sequence[str] | None = None,
        sort_direction: Literal["asc", "desc"] = "asc",
        group_by: Literal["none", "state", "due_week"] = "none",
    ) -> OverdueTaskPage:
        if scope == "aggregate":
            if project_id is None:
                self.authorization.require(
                    actor, "schedule.manage", self._scope(organization_id, workspace_id)
                )
            else:
                self.projects.require_access(
                    actor, organization_id, workspace_id, project_id, "schedule.manage"
                )
        else:
            if project_id is None:
                self.authorization.require(
                    actor, "task.read", self._scope(organization_id, workspace_id)
                )
            else:
                self.projects.require_access(
                    actor, organization_id, workspace_id, project_id, "task.read"
                )
        query_filters = [
            TaskQueryFilter(field=item.field, operator=item.operator, value=item.value)
            for item in (filters or [])
        ]
        if group_by == "state":
            counts = self.tasks.inbox_state_counts(
                actor,
                organization_id,
                workspace_id,
                project_id,
                "project" if scope == "aggregate" else "personal",
                query_filters,
            )
            return OverdueTaskPage(
                items=[],
                next_cursor=None,
                groups=[TaskStateGroup(state=item.state, count=item.count) for item in counts],
                due_week_groups=[],
            )
        if group_by == "due_week":
            now = datetime.now(UTC)
            current_week = now.date() - timedelta(days=now.weekday())
            first_week = current_week - timedelta(weeks=11)
            period_start = datetime.combine(first_week, datetime.min.time(), UTC)
            due_counts = self.tasks.inbox_due_week_counts(
                actor,
                organization_id,
                workspace_id,
                project_id,
                "project" if scope == "aggregate" else "personal",
                now,
                period_start,
                query_filters,
            )
            by_week = {item.week_start: item.count for item in due_counts if item.week_start}
            older_count = next((item.count for item in due_counts if item.week_start is None), 0)
            weeks = [first_week + timedelta(weeks=index) for index in range(12)]
            return OverdueTaskPage(
                items=[],
                next_cursor=None,
                groups=[],
                due_week_groups=[
                    DueWeekGroup(
                        week_start=None,
                        label=f"Before {first_week.isoformat()}",
                        count=older_count,
                    ),
                    *[
                        DueWeekGroup(
                            week_start=week,
                            label=week.isoformat(),
                            count=by_week.get(week, 0),
                        )
                        for week in weeks
                    ],
                ],
            )
        tasks, next_cursor = self.tasks.inbox(
            actor,
            organization_id,
            workspace_id,
            project_id,
            "overdue",
            "project" if scope == "aggregate" else "personal",
            None,
            cursor,
            query_filters,
            sort_direction=sort_direction,
        )
        items = [
            OverdueTaskRow(
                id=task.id,
                project_id=task.project_id,
                kind=task.kind,
                name=task.name,
                state=task.state,
                due_at=task.due_at,
            )
            for task in tasks
        ]
        selected = set(columns or ["id", "project_id", "kind", "name", "state", "due_at"])
        items = [
            row.model_copy(
                update={
                    field: getattr(row, field) if field in selected else None
                    for field in ("id", "project_id", "kind", "name", "state", "due_at")
                }
            )
            for row in items
        ]
        return OverdueTaskPage(
            items=items,
            next_cursor=next_cursor,
            groups=[],
            due_week_groups=[],
        )

    def overdue_tasks(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None,
        scope: Literal["personal", "aggregate"],
        cursor: UUID | None,
    ) -> OverdueTaskPage:
        self._access(actor, organization_id, workspace_id, project_id)
        return self._read(actor, organization_id, workspace_id, project_id, scope, cursor)

    def _audit(
        self,
        actor: RequestContext,
        organization_id: UUID,
        actor_id: UUID,
        report: SavedReport,
        kind: str,
        version: int,
    ) -> UUID:
        audit_id = uuid7()
        self.audit.append(
            AuditEvent(
                id=audit_id,
                type=f"report.saved_definition.{kind}",
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor_id=actor_id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type="saved_report",
                aggregate_id=report.id,
                payload=AuditDetails(
                    target_id=report.id,
                    workspace_id=report.workspace_id,
                    project_id=report.project_id,
                    version=version,
                ),
            )
        )
        return audit_id

    def list_saved(
        self, actor: RequestContext, organization_id: UUID, workspace_id: UUID, cursor: UUID | None
    ) -> SavedReportPage:
        self._access(actor, organization_id, workspace_id, None)
        owner_id = self._actor(actor, organization_id)
        reports = self.reports.page(organization_id, workspace_id, owner_id, cursor)
        return SavedReportPage(
            items=reports[:100], next_cursor=reports[99].id if len(reports) > 100 else None
        )

    def get_saved(
        self, actor: RequestContext, organization_id: UUID, report_id: UUID
    ) -> SavedReport:
        report = self.reports.get(organization_id, report_id)
        if report is None or report.archived:
            raise ServiceError(404, "not_found")
        self._access(actor, organization_id, report.workspace_id, report.project_id)
        if report.owner_id != self._actor(actor, organization_id):
            raise ServiceError(404, "not_found")
        return report

    def create_saved(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None,
        body: SavedReportWrite,
    ) -> SavedReport:
        self._access(actor, organization_id, workspace_id, project_id)
        owner_id = self._actor(actor, organization_id)
        now = datetime.now(UTC)
        identifier = uuid7()
        digest = self._digest(body.definition)
        report = SavedReport(
            id=identifier,
            organization_id=organization_id,
            workspace_id=workspace_id,
            project_id=project_id,
            owner_id=owner_id,
            name=body.name,
            definition=body.definition,
            version=1,
            definition_sha256=digest,
            created_at=now,
            updated_at=now,
            audit_id=uuid7(),
        )
        audit_id = report.audit_id
        self.audit.append(
            AuditEvent(
                id=audit_id,
                type="report.saved_definition.created",
                occurred_at=report.created_at,
                organization_id=organization_id,
                actor_id=owner_id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type="saved_report",
                aggregate_id=report.id,
                payload=AuditDetails(
                    target_id=report.id,
                    workspace_id=report.workspace_id,
                    project_id=report.project_id,
                    version=report.version,
                ),
            )
        )
        self.reports.create(report)
        return report

    def update_saved(
        self, actor: RequestContext, organization_id: UUID, report_id: UUID, body: SavedReportWrite
    ) -> SavedReport:
        if body.expected_version is None:
            raise ServiceError(422, "expected_version_required")
        current = self.get_saved(actor, organization_id, report_id)
        if current.version != body.expected_version:
            raise ServiceError(409, "version_conflict")
        now = datetime.now(UTC)
        changed = current.model_copy(
            update={
                "name": body.name,
                "definition": body.definition,
                "version": current.version + 1,
                "created_at": now,
                "updated_at": now,
                "definition_sha256": self._digest(body.definition),
                "audit_id": uuid7(),
            }
        )
        audit_id = changed.audit_id
        self.audit.append(
            AuditEvent(
                id=audit_id,
                type="report.saved_definition.updated",
                occurred_at=now,
                organization_id=organization_id,
                actor_id=current.owner_id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type="saved_report",
                aggregate_id=changed.id,
                payload=AuditDetails(
                    target_id=changed.id,
                    workspace_id=changed.workspace_id,
                    project_id=changed.project_id,
                    version=changed.version,
                ),
            )
        )
        if not self.reports.append(changed, current.version):
            raise ServiceError(409, "version_conflict")
        return changed

    def archive_saved(
        self, actor: RequestContext, organization_id: UUID, report_id: UUID, expected_version: int
    ) -> None:
        current = self.get_saved(actor, organization_id, report_id)
        if current.version != expected_version:
            raise ServiceError(409, "version_conflict")
        now = datetime.now(UTC)
        audit_id = uuid7()
        self.audit.append(
            AuditEvent(
                id=audit_id,
                type="report.saved_definition.archived",
                occurred_at=now,
                organization_id=organization_id,
                actor_id=current.owner_id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type="saved_report",
                aggregate_id=report_id,
                payload=AuditDetails(
                    target_id=report_id,
                    workspace_id=current.workspace_id,
                    project_id=current.project_id,
                    version=current.version,
                ),
            )
        )
        if not self.reports.archive(
            organization_id, report_id, current.owner_id, expected_version, now, audit_id
        ):
            raise ServiceError(409, "version_conflict")

    def run_saved(
        self, actor: RequestContext, organization_id: UUID, report_id: UUID, cursor: UUID | None
    ) -> OverdueTaskPage:
        report = self.get_saved(actor, organization_id, report_id)
        return self._run_definition(actor, organization_id, report, cursor)

    def _run_definition(
        self,
        actor: RequestContext,
        organization_id: UUID,
        report: SavedReport,
        cursor: UUID | None,
    ) -> OverdueTaskPage:
        return self._read(
            actor,
            organization_id,
            report.workspace_id,
            report.project_id,
            report.definition.scope,
            cursor,
            report.definition.filters,
            report.definition.columns,
            report.definition.sort_direction,
            report.definition.group_by,
        )

    def export_saved(
        self,
        actor: RequestContext,
        organization_id: UUID,
        report_id: UUID,
        format: Literal["csv", "xlsx", "pdf"],
    ) -> ReportExport:
        report = self.get_saved(actor, organization_id, report_id)
        page = self._run_definition(actor, organization_id, report, None)
        if page.next_cursor is not None:
            raise ServiceError(409, "export_requires_background_job")
        if report.definition.group_by == "state":
            columns = ["state", "count"]
            rows = [[group.state, str(group.count)] for group in page.groups]
        elif report.definition.group_by == "due_week":
            columns = ["due_week", "count"]
            rows = [[group.label, str(group.count)] for group in page.due_week_groups]
        else:
            columns = list(report.definition.columns)
            rows = [
                [self._export_value(getattr(item, column)) for column in columns]
                for item in page.items
            ]
        media_type = self._media_type(format)
        return ReportExport(
            file_name=f"overdue-tasks-{report.id}.{format}",
            media_type=media_type,
            content=self.renderer.render(columns, rows, format),
        )

    def create_export_job(
        self,
        actor: RequestContext,
        organization_id: UUID,
        report_id: UUID,
        format: Literal["csv", "xlsx", "pdf"],
    ) -> ReportExportJob:
        if self.export_jobs is None:
            raise ServiceError(503, "report_export_jobs_unavailable")
        report = self.get_saved(actor, organization_id, report_id)
        now = datetime.now(UTC)
        job = ReportExportJob(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=report.workspace_id,
            project_id=report.project_id,
            owner_id=report.owner_id,
            report_id=report.id,
            report_version=report.version,
            report_digest=report.definition_sha256,
            scope=report.definition.scope,
            format=format,
            state="pending",
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=24),
        )
        definition = report.definition.model_dump(mode="json")
        self.export_jobs.create(job, definition)
        self._export_audit(actor, job, "queued")
        return job

    def list_export_jobs(
        self, actor: RequestContext, organization_id: UUID, workspace_id: UUID
    ) -> list[ReportExportJob]:
        if self.export_jobs is None:
            raise ServiceError(503, "report_export_jobs_unavailable")
        self._access(actor, organization_id, workspace_id, None)
        owner = self._actor(actor, organization_id)
        return self.export_jobs.page(organization_id, workspace_id, owner)

    def get_export_job(
        self, actor: RequestContext, organization_id: UUID, job_id: UUID
    ) -> ReportExportJob:
        if self.export_jobs is None:
            raise ServiceError(503, "report_export_jobs_unavailable")
        job = self.export_jobs.get(organization_id, job_id)
        if job is None or job.owner_id != self._actor(actor, organization_id):
            raise ServiceError(404, "not_found")
        self._access(actor, organization_id, job.workspace_id, job.project_id)
        self._dataset_access(actor, organization_id, job.workspace_id, job.project_id, job.scope)
        if job.expires_at <= datetime.now(UTC):
            raise ServiceError(410, "report_export_expired")
        return job

    def _dataset_access(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None,
        scope: Literal["personal", "aggregate"],
    ) -> None:
        permission = "schedule.manage" if scope == "aggregate" else "task.read"
        if project_id is None:
            self.authorization.require(
                actor, permission, self._scope(organization_id, workspace_id)
            )
        else:
            self.projects.require_access(
                actor, organization_id, workspace_id, project_id, permission
            )

    def run_export_job(
        self,
        actor: RequestContext,
        organization_id: UUID,
        job_id: UUID,
        store: ReportExportJobStore,
        artifact_store: PrivateStorage,
    ) -> ReportExportJob | None:
        job = store.get(organization_id, job_id, lock=True)
        if job is None or job.state in {"completed", "expired", "revoked"}:
            return job
        if job.expires_at <= datetime.now(UTC):
            expired = job.model_copy(update={"state": "expired", "updated_at": datetime.now(UTC)})
            store.save(expired, job.state)
            return expired
        report = self.reports.get(organization_id, job.report_id)
        if report is None or report.owner_id != job.owner_id:
            changed = job.model_copy(update={"state": "revoked", "updated_at": datetime.now(UTC)})
            store.save(changed, job.state)
            return changed
        # Execute the pinned immutable definition, while authorization remains current.
        from operations.modules.reporting.application.contracts import SavedReportDefinition

        raw_definition = store.definition(organization_id, job_id)
        if raw_definition is None:
            raise ServiceError(409, "report_export_definition_missing")
        definition = SavedReportDefinition.model_validate(raw_definition)
        if self._digest(definition) != job.report_digest:
            raise ServiceError(409, "report_export_definition_integrity")
        pinned = report.model_copy(
            update={
                "definition": definition,
                "version": job.report_version,
                "definition_sha256": job.report_digest,
            }
        )
        claimed = store.claim(organization_id, job_id, datetime.now(UTC))
        if claimed is None:
            return store.get(organization_id, job_id)
        job = claimed
        try:
            self._dataset_access(
                actor, organization_id, job.workspace_id, job.project_id, job.scope
            )
            page = self._run_definition(actor, organization_id, pinned, None)
        except ServiceError as error:
            changed = job.model_copy(
                update={
                    "state": "revoked",
                    "updated_at": datetime.now(UTC),
                    "error_code": error.code,
                }
            )
            store.save(changed, job.state)
            self._export_audit(actor, changed, "revoked")
            return changed
        columns, rows = self._export_matrix(pinned, page)
        cursor = page.next_cursor
        while cursor is not None:
            next_page = self._run_definition(actor, organization_id, pinned, cursor)
            next_columns, next_rows = self._export_matrix(pinned, next_page)
            if next_columns != columns:
                raise ServiceError(409, "report_export_columns_changed")
            rows.extend(next_rows)
            if len(rows) > 10000:
                raise ServiceError(413, "report_export_row_limit")
            cursor = next_page.next_cursor
        content = self.renderer.render(columns, rows, job.format)
        if len(content) > 50_000_000:
            raise ServiceError(413, "report_export_size_limit")
        digest = hashlib.sha256(content).hexdigest()
        key = f"organizations/{organization_id}/report-exports/{job.id}.{job.format}"
        artifact_store.put(key, content, self._media_type(job.format))
        completed = job.model_copy(
            update={
                "state": "completed",
                "updated_at": datetime.now(UTC),
                "artifact_key": key,
                "artifact_sha256": digest,
                "artifact_size": len(content),
            }
        )
        store.save(completed, "running")
        self._export_audit(actor, completed, "completed")
        return completed

    @staticmethod
    def _export_matrix(
        report: SavedReport, page: OverdueTaskPage
    ) -> tuple[list[str], list[list[str]]]:
        if report.definition.group_by == "state":
            return ["state", "count"], [[item.state, str(item.count)] for item in page.groups]
        if report.definition.group_by == "due_week":
            return ["due_week", "count"], [
                [item.label, str(item.count)] for item in page.due_week_groups
            ]
        columns = [str(column) for column in report.definition.columns]
        rows = [
            [ReportingService._export_value(getattr(item, column)) for column in columns]
            for item in page.items
        ]
        return columns, rows

    @staticmethod
    def _media_type(format: Literal["csv", "xlsx", "pdf"]) -> str:
        return {
            "csv": "text/csv; charset=utf-8",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pdf": "application/pdf",
        }[format]

    def _export_audit(self, actor: RequestContext, job: ReportExportJob, kind: str) -> None:
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type=f"report.export.{kind}",
                occurred_at=datetime.now(UTC),
                organization_id=job.organization_id,
                actor_id=job.owner_id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type="report_export",
                aggregate_id=job.id,
                payload=AuditDetails(
                    target_id=job.report_id, workspace_id=job.workspace_id, reason=kind
                ),
            )
        )

    @staticmethod
    def _export_value(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def list_dashboards(
        self, actor: RequestContext, organization_id: UUID, workspace_id: UUID, cursor: UUID | None
    ) -> DashboardPage:
        self._access(actor, organization_id, workspace_id, None)
        rows = self.dashboards.page(
            organization_id, workspace_id, self._actor(actor, organization_id), cursor
        )
        return DashboardPage(items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None)

    def get_dashboard(
        self, actor: RequestContext, organization_id: UUID, dashboard_id: UUID
    ) -> Dashboard:
        dashboard = self.dashboards.get(organization_id, dashboard_id)
        if dashboard is None or dashboard.archived:
            raise ServiceError(404, "not_found")
        self._access(actor, organization_id, dashboard.workspace_id, None)
        if dashboard.owner_id != self._actor(actor, organization_id):
            raise ServiceError(404, "not_found")
        return dashboard

    def _validate_dashboard(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        owner_id: UUID,
        definition: DashboardDefinition,
    ) -> None:
        for widget in definition.widgets:
            report = self.get_saved(actor, organization_id, widget.report_id)
            if report.workspace_id != workspace_id or report.owner_id != owner_id:
                raise ServiceError(404, "not_found")
            state_chart = widget.kind in {"status_distribution", "bar", "metric"}
            time_chart = widget.kind in {"trend", "line"}
            if state_chart and report.definition.group_by != "state":
                raise ServiceError(422, "status_distribution_requires_state_grouping")
            if time_chart and report.definition.group_by != "due_week":
                raise ServiceError(422, "trend_requires_due_week_grouping")
            if widget.kind in {"table", "overdue_list"} and report.definition.group_by != "none":
                raise ServiceError(422, "row_widget_requires_ungrouped_report")

    def create_dashboard(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        body: DashboardWrite,
    ) -> Dashboard:
        self._access(actor, organization_id, workspace_id, None)
        owner_id = self._actor(actor, organization_id)
        self._validate_dashboard(actor, organization_id, workspace_id, owner_id, body.definition)
        now = datetime.now(UTC)
        dashboard = Dashboard(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
            name=body.name,
            definition=body.definition,
            version=1,
            definition_sha256=self._dashboard_digest(body.definition),
            created_at=now,
            updated_at=now,
            audit_id=uuid7(),
        )
        self._dashboard_audit(actor, dashboard, "created", dashboard.audit_id, now)
        self.dashboards.create(dashboard)
        return dashboard

    def update_dashboard(
        self,
        actor: RequestContext,
        organization_id: UUID,
        dashboard_id: UUID,
        body: DashboardWrite,
    ) -> Dashboard:
        if body.expected_version is None:
            raise ServiceError(422, "expected_version_required")
        current = self.get_dashboard(actor, organization_id, dashboard_id)
        if current.version != body.expected_version:
            raise ServiceError(409, "version_conflict")
        self._validate_dashboard(
            actor, organization_id, current.workspace_id, current.owner_id, body.definition
        )
        now, audit_id = datetime.now(UTC), uuid7()
        updated = current.model_copy(
            update={
                "name": body.name,
                "definition": body.definition,
                "version": current.version + 1,
                "created_at": now,
                "updated_at": now,
                "definition_sha256": self._dashboard_digest(body.definition),
                "audit_id": audit_id,
            }
        )
        self._dashboard_audit(actor, updated, "updated", audit_id, now)
        if not self.dashboards.append(updated, current.version):
            raise ServiceError(409, "version_conflict")
        return updated

    def archive_dashboard(
        self, actor: RequestContext, organization_id: UUID, dashboard_id: UUID, expected: int
    ) -> None:
        current = self.get_dashboard(actor, organization_id, dashboard_id)
        if current.version != expected:
            raise ServiceError(409, "version_conflict")
        now, audit_id = datetime.now(UTC), uuid7()
        self._dashboard_audit(actor, current, "archived", audit_id, now)
        if not self.dashboards.archive(
            organization_id, dashboard_id, current.owner_id, expected, now, audit_id
        ):
            raise ServiceError(409, "version_conflict")

    def run_dashboard(
        self, actor: RequestContext, organization_id: UUID, dashboard_id: UUID
    ) -> DashboardResult:
        dashboard = self.get_dashboard(actor, organization_id, dashboard_id)
        widgets: list[DashboardWidgetResult] = []
        for widget in dashboard.definition.widgets:
            report = self.run_saved(actor, organization_id, widget.report_id, None)
            metric_value = (
                sum(group.count for group in report.groups) if widget.kind == "metric" else None
            )
            widgets.append(
                DashboardWidgetResult(
                    title=widget.title,
                    kind=widget.kind,
                    report=report,
                    metric_value=metric_value,
                )
            )
        return DashboardResult(
            dashboard_id=dashboard.id, version=dashboard.version, widgets=widgets
        )

    def _dashboard_audit(
        self,
        actor: RequestContext,
        dashboard: Dashboard,
        kind: str,
        audit_id: UUID,
        occurred_at: datetime,
    ) -> None:
        self.audit.append(
            AuditEvent(
                id=audit_id,
                type=f"report.dashboard.{kind}",
                occurred_at=occurred_at,
                organization_id=dashboard.organization_id,
                actor_id=dashboard.owner_id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type="dashboard",
                aggregate_id=dashboard.id,
                payload=AuditDetails(
                    target_id=dashboard.id,
                    workspace_id=dashboard.workspace_id,
                    version=dashboard.version,
                ),
            )
        )

    @staticmethod
    def _dashboard_digest(definition: DashboardDefinition) -> str:
        content = json.dumps(
            definition.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def _digest(definition: SavedReportDefinition) -> str:
        content = json.dumps(
            definition.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(content.encode()).hexdigest()
