from datetime import UTC, datetime, timedelta

import pytest
from operations.modules.scheduling.application.contracts import Assignment, Recurrence
from operations.modules.scheduling.domain.recurrence import (
    expand,
    intervals,
    local_instant,
    parse_rule,
)
from pydantic import ValidationError


def test_dst_gaps_overlaps_and_wall_time_preservation() -> None:
    assert local_instant(datetime(2026, 3, 8, 2, 30), "America/New_York") is None
    assert local_instant(datetime(2026, 11, 1, 1, 30), "America/New_York") == datetime(
        2026, 11, 1, 5, 30, tzinfo=UTC
    )
    rows = expand(
        datetime(2026, 3, 7, 2, 30),
        "America/New_York",
        parse_rule("FREQ=DAILY;COUNT=3"),
        datetime(2026, 3, 7, tzinfo=UTC),
        datetime(2026, 3, 12, tzinfo=UTC),
    )
    assert [row.day for row in rows] == [7, 9, 10]
    assert [row.hour for row in rows] == [7, 6, 6]


def test_month_dates_week_start_and_selectors() -> None:
    rows = expand(
        datetime(2026, 1, 31, 9),
        "UTC",
        parse_rule("FREQ=MONTHLY"),
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert len(rows) == 1 and rows[0].day == 31
    rows = expand(
        datetime(2026, 10, 1, 9),
        "UTC",
        parse_rule("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR;COUNT=4"),
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 11, 1, tzinfo=UTC),
    )
    assert [x.day for x in rows] == [2, 12, 16, 26]
    rows = expand(
        datetime(2026, 1, 1, 9),
        "UTC",
        parse_rule("FREQ=MONTHLY;BYMONTHDAY=-1"),
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert [x.day for x in rows] == [31, 28]


def test_intervals_use_elapsed_time_and_half_open_windows() -> None:
    anchor = datetime(2026, 3, 7, 12, tzinfo=UTC)
    assert intervals(anchor, 86400, anchor + timedelta(seconds=1), anchor + timedelta(days=3)) == [
        anchor + timedelta(days=1),
        anchor + timedelta(days=2),
    ]
    with pytest.raises(ValueError):
        intervals(anchor, 1, anchor, anchor + timedelta(days=2))
    with pytest.raises(ValueError):
        expand(
            datetime(2000, 1, 1),
            "UTC",
            parse_rule("FREQ=DAILY"),
            anchor,
            anchor + timedelta(days=1),
        )


@pytest.mark.parametrize(
    "rule",
    [
        "FREQ=SECONDLY",
        "FREQ=DAILY;COUNT=2;UNTIL=20261007T000000Z",
        "FREQ=DAILY;BYDAY=1MO",
        "FREQ=WEEKLY;BYMONTHDAY=1",
        "FREQ=DAILY;BYMONTH=13",
        "FREQ=DAILY;INTERVAL=0",
        "FREQ=DAILY;FREQ=WEEKLY",
        "FREQ=DAILY;BYSETPOS=1",
        "FREQ=DAILY;BYDAY=MO,MO",
    ],
)
def test_unsafe_or_unsupported_rules_reject(rule: str) -> None:
    with pytest.raises(ValueError):
        parse_rule(rule)


def test_typed_targets_and_invalid_timezone() -> None:
    with pytest.raises(ValidationError):
        Assignment(kind="user")
    with pytest.raises(ValidationError):
        Recurrence(kind="daily", timezone="missing/zone", starts_local=datetime(2026, 10, 6))
