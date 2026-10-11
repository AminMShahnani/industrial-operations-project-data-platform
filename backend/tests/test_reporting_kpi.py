from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.reporting.application.contracts import (
    SavedKpiDefinition,
    SavedReport,
    SavedReportDefinition,
)
from operations.modules.reporting.application.datasets import ReportingService
from operations.modules.submissions.application.contracts import (
    SubmissionAggregateGroup,
    SubmissionAggregateQuery,
    SubmissionAggregateResult,
)
from operations.modules.submissions.application.service import SubmissionService


class _Submissions:
    def __init__(self) -> None:
        self.query: SubmissionAggregateQuery | None = None

    def aggregate(
        self,
        _actor: RequestContext,
        _org: object,
        _workspace: object,
        query: SubmissionAggregateQuery,
    ) -> SubmissionAggregateResult:
        self.query = query
        return SubmissionAggregateResult(
            start_date=query.start_date,
            end_date=query.end_date,
            groups=[SubmissionAggregateGroup(group="well-a", value=4.5)],
        )


def test_pack_kpi_report_executes_only_its_pinned_source_form_window() -> None:
    service = object.__new__(ReportingService)
    submissions = _Submissions()
    service.submissions = cast(SubmissionService, submissions)
    form_id = uuid4()
    now = datetime.now(UTC)
    kpi = SavedKpiDefinition(
        metric="average",
        source_form=form_id,
        source_form_number=2,
        source_field="rop",
        unit="m/h",
        time_field="report_date",
        group_field="well_name",
        window_days=31,
    )
    definition = SavedReportDefinition(
        dataset="pack_form_kpi",
        scope="aggregate",
        columns=[],
        kpi=kpi,
    )
    report = SavedReport(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        project_id=None,
        owner_id=uuid4(),
        name="Rate of penetration",
        definition=definition,
        version=1,
        definition_sha256="a" * 64,
        created_at=now,
        updated_at=now,
        audit_id=uuid4(),
    )
    actor = RequestContext(Principal("https://issuer.test", "owner"), uuid4(), uuid4())

    result = service._run_definition(actor, report.organization_id, report, None)

    query = submissions.query
    assert query is not None
    assert query.form_id == form_id and query.form_number == 2
    assert query.metric == "average" and query.source_field == "rop"
    assert query.group_field == "well_name"
    assert (query.end_date - query.start_date).days == 30
    assert result.kpi_result is not None
    assert result.kpi_result.unit == "m/h"
    assert result.kpi_result.groups[0].value == 4.5


def test_kpi_report_definition_requires_aggregate_scope_and_no_row_columns() -> None:
    import pytest
    from pydantic import ValidationError

    kpi = SavedKpiDefinition(
        metric="count",
        source_form=uuid4(),
        unit="submissions",
        time_field="report_date",
        window_days=7,
    )
    with pytest.raises(ValidationError, match="invalid_pack_kpi_report_definition"):
        SavedReportDefinition(
            dataset="pack_form_kpi",
            scope="personal",
            columns=[],
            kpi=kpi,
        )
