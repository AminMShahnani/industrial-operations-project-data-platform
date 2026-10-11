from typing import Literal
from uuid import UUID, uuid7

from dramatiq import Message
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from operations.api import Context, ServiceDependency
from operations.modules.reporting.application.contracts import (
    Dashboard,
    DashboardPage,
    DashboardResult,
    DashboardWrite,
    OverdueTaskPage,
    ReportExportJob,
    SavedReport,
    SavedReportPage,
    SavedReportWrite,
)

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports",
    tags=["reporting"],
)


class ExportRequest(BaseModel):
    format: Literal["csv", "xlsx", "pdf"]


@router.get("/overdue-tasks", response_model=OverdueTaskPage)
def overdue_tasks(
    organization_id: UUID,
    workspace_id: UUID,
    context: Context,
    services: ServiceDependency,
    scope: Literal["personal", "aggregate"] = "personal",
    project_id: UUID | None = None,
    cursor: UUID | None = None,
) -> OverdueTaskPage:
    return services.reporting.overdue_tasks(
        context, organization_id, workspace_id, project_id, scope, cursor
    )


@router.get("/saved", response_model=SavedReportPage)
def list_saved(
    organization_id: UUID,
    workspace_id: UUID,
    context: Context,
    services: ServiceDependency,
    cursor: UUID | None = None,
) -> SavedReportPage:
    return services.reporting.list_saved(context, organization_id, workspace_id, cursor)


@router.post("/saved", response_model=SavedReport, status_code=201)
def create_saved(
    organization_id: UUID,
    workspace_id: UUID,
    body: SavedReportWrite,
    context: Context,
    services: ServiceDependency,
    project_id: UUID | None = None,
) -> SavedReport:
    return services.reporting.create_saved(context, organization_id, workspace_id, project_id, body)


@router.get("/saved/{report_id}", response_model=SavedReport)
def get_saved(
    organization_id: UUID,
    workspace_id: UUID,
    report_id: UUID,
    context: Context,
    services: ServiceDependency,
) -> SavedReport:
    report = services.reporting.get_saved(context, organization_id, report_id)
    if report.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    return report


@router.put("/saved/{report_id}", response_model=SavedReport)
def update_saved(
    organization_id: UUID,
    workspace_id: UUID,
    report_id: UUID,
    body: SavedReportWrite,
    context: Context,
    services: ServiceDependency,
) -> SavedReport:
    report = services.reporting.get_saved(context, organization_id, report_id)
    if report.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    return services.reporting.update_saved(context, organization_id, report_id, body)


@router.post("/saved/{report_id}/archive", status_code=204)
def archive_saved(
    organization_id: UUID,
    workspace_id: UUID,
    report_id: UUID,
    context: Context,
    services: ServiceDependency,
    expected_version: int,
) -> Response:
    report = services.reporting.get_saved(context, organization_id, report_id)
    if report.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    services.reporting.archive_saved(context, organization_id, report_id, expected_version)
    return Response(status_code=204)


@router.get("/saved/{report_id}/run", response_model=OverdueTaskPage)
def run_saved(
    organization_id: UUID,
    workspace_id: UUID,
    report_id: UUID,
    context: Context,
    services: ServiceDependency,
    cursor: UUID | None = None,
) -> OverdueTaskPage:
    report = services.reporting.get_saved(context, organization_id, report_id)
    if report.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    return services.reporting.run_saved(context, organization_id, report_id, cursor)


@router.get(
    "/saved/{report_id}/export",
    response_class=Response,
    responses={
        200: {
            "content": {
                "text/csv": {"schema": {"type": "string", "format": "binary"}},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                    "schema": {"type": "string", "format": "binary"}
                },
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
def export_saved(
    organization_id: UUID,
    workspace_id: UUID,
    report_id: UUID,
    context: Context,
    services: ServiceDependency,
    format: Literal["csv", "xlsx", "pdf"],
) -> Response:
    report = services.reporting.get_saved(context, organization_id, report_id)
    if report.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    artifact = services.reporting.export_saved(context, organization_id, report_id, format)
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.file_name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/saved/{report_id}/export-jobs", response_model=ReportExportJob, status_code=202)
def create_export_job(
    organization_id: UUID,
    workspace_id: UUID,
    report_id: UUID,
    body: ExportRequest,
    context: Context,
    services: ServiceDependency,
    request: Request,
) -> ReportExportJob:
    report = services.reporting.get_saved(context, organization_id, report_id)
    if report.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    job = services.reporting.create_export_job(context, organization_id, report_id, body.format)
    request.app.state.job_broker.enqueue(
        Message(
            queue_name="operations",
            actor_name="consume_report_export",
            args=(str(organization_id), str(job.id)),
            kwargs={},
            options={"max_retries": 3},
            message_id=str(uuid7()),
        )
    )
    return job


@router.get("/export-jobs", response_model=list[ReportExportJob])
def list_export_jobs(
    organization_id: UUID,
    workspace_id: UUID,
    context: Context,
    services: ServiceDependency,
) -> list[ReportExportJob]:
    return services.reporting.list_export_jobs(context, organization_id, workspace_id)


@router.get("/export-jobs/{job_id}", response_model=ReportExportJob)
def get_export_job(
    organization_id: UUID,
    workspace_id: UUID,
    job_id: UUID,
    context: Context,
    services: ServiceDependency,
) -> ReportExportJob:
    job = services.reporting.get_export_job(context, organization_id, job_id)
    if job.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    return job


@router.get("/export-jobs/{job_id}/download", response_class=Response)
def download_export_job(
    organization_id: UUID,
    workspace_id: UUID,
    job_id: UUID,
    context: Context,
    services: ServiceDependency,
) -> Response:
    job = services.reporting.get_export_job(context, organization_id, job_id)
    if job.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    if job.state != "completed" or not job.artifact_key:
        from operations.contracts import ServiceError

        raise ServiceError(409, "report_export_not_ready")
    content = services.files.storage.get(job.artifact_key)
    import hashlib

    if (
        hashlib.sha256(content).hexdigest() != job.artifact_sha256
        or len(content) != job.artifact_size
    ):
        from operations.contracts import ServiceError

        raise ServiceError(409, "report_export_artifact_integrity")
    media = {
        "csv": "text/csv; charset=utf-8",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
    }[job.format]
    return Response(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="report-{job.report_id}.{job.format}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/dashboards", response_model=DashboardPage)
def list_dashboards(
    organization_id: UUID,
    workspace_id: UUID,
    context: Context,
    services: ServiceDependency,
    cursor: UUID | None = None,
) -> DashboardPage:
    return services.reporting.list_dashboards(context, organization_id, workspace_id, cursor)


@router.post("/dashboards", response_model=Dashboard, status_code=201)
def create_dashboard(
    organization_id: UUID,
    workspace_id: UUID,
    body: DashboardWrite,
    context: Context,
    services: ServiceDependency,
) -> Dashboard:
    return services.reporting.create_dashboard(context, organization_id, workspace_id, body)


@router.get("/dashboards/{dashboard_id}", response_model=Dashboard)
def get_dashboard(
    organization_id: UUID,
    workspace_id: UUID,
    dashboard_id: UUID,
    context: Context,
    services: ServiceDependency,
) -> Dashboard:
    dashboard = services.reporting.get_dashboard(context, organization_id, dashboard_id)
    if dashboard.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    return dashboard


@router.put("/dashboards/{dashboard_id}", response_model=Dashboard)
def update_dashboard(
    organization_id: UUID,
    workspace_id: UUID,
    dashboard_id: UUID,
    body: DashboardWrite,
    context: Context,
    services: ServiceDependency,
) -> Dashboard:
    dashboard = services.reporting.get_dashboard(context, organization_id, dashboard_id)
    if dashboard.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    return services.reporting.update_dashboard(context, organization_id, dashboard_id, body)


@router.post("/dashboards/{dashboard_id}/archive", status_code=204)
def archive_dashboard(
    organization_id: UUID,
    workspace_id: UUID,
    dashboard_id: UUID,
    context: Context,
    services: ServiceDependency,
    expected_version: int,
) -> Response:
    dashboard = services.reporting.get_dashboard(context, organization_id, dashboard_id)
    if dashboard.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    services.reporting.archive_dashboard(context, organization_id, dashboard_id, expected_version)
    return Response(status_code=204)


@router.get("/dashboards/{dashboard_id}/run", response_model=DashboardResult)
def run_dashboard(
    organization_id: UUID,
    workspace_id: UUID,
    dashboard_id: UUID,
    context: Context,
    services: ServiceDependency,
) -> DashboardResult:
    dashboard = services.reporting.get_dashboard(context, organization_id, dashboard_id)
    if dashboard.workspace_id != workspace_id:
        from operations.contracts import ServiceError

        raise ServiceError(404, "not_found")
    return services.reporting.run_dashboard(context, organization_id, dashboard_id)
