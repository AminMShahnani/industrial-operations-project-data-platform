from datetime import date, timedelta
from uuid import uuid4

import pytest
from operations.modules.submissions.application.contracts import SubmissionAggregateQuery
from pydantic import ValidationError


def test_form_kpi_aggregate_query_accepts_at_most_366_calendar_days() -> None:
    today = date(2026, 10, 11)
    query = SubmissionAggregateQuery(
        form_id=uuid4(),
        form_number=1,
        time_field="occurred_on",
        start_date=today - timedelta(days=365),
        end_date=today,
        metric="count",
    )
    assert (query.end_date - query.start_date).days == 365

    with pytest.raises(ValidationError, match="aggregate_window_exceeds_366_days"):
        SubmissionAggregateQuery(
            form_id=uuid4(),
            form_number=1,
            time_field="occurred_on",
            start_date=today - timedelta(days=366),
            end_date=today,
            metric="count",
        )


def test_numeric_form_kpi_requires_a_source_field() -> None:
    with pytest.raises(ValidationError, match="aggregate_source_field_required"):
        SubmissionAggregateQuery(
            form_id=uuid4(),
            form_number=1,
            time_field="occurred_on",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 11),
            metric="average",
        )
