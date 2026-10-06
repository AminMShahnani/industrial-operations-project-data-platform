"""Bounded wall-clock recurrence. No framework, source execution or unbounded iterators."""

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


@dataclass(frozen=True)
class Rule:
    frequency: str
    interval: int = 1
    count: int | None = None
    until: datetime | None = None
    weekdays: tuple[int, ...] = ()
    monthdays: tuple[int, ...] = ()
    months: tuple[int, ...] = ()


def parse_rule(source: str) -> Rule:
    if len(source) > 300:
        raise ValueError("Rule too long")
    parts: dict[str, str] = {}
    for part in source.split(";"):
        key, separator, value = part.partition("=")
        if not separator or not value or key in parts:
            raise ValueError("Malformed recurrence")
        parts[key] = value
    if set(parts) - {
        "FREQ",
        "INTERVAL",
        "COUNT",
        "UNTIL",
        "BYDAY",
        "BYMONTHDAY",
        "BYMONTH",
        "WKST",
    }:
        raise ValueError("Unsupported recurrence part")
    freq = parts.get("FREQ", "")
    if freq not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"} or parts.get("WKST", "MO") != "MO":
        raise ValueError("Unsupported frequency/week start")
    interval = int(parts.get("INTERVAL", "1"))
    count = int(parts["COUNT"]) if "COUNT" in parts else None
    until = (
        datetime.strptime(parts["UNTIL"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if "UNTIL" in parts
        else None
    )
    if (
        not 1 <= interval <= 366
        or (count is not None and not 1 <= count <= 10000)
        or (count and until)
    ):
        raise ValueError("Invalid recurrence bounds")
    days = (
        tuple(WEEKDAYS.index(day) for day in parts["BYDAY"].split(",")) if "BYDAY" in parts else ()
    )
    mdays = (
        tuple(int(day) for day in parts["BYMONTHDAY"].split(",")) if "BYMONTHDAY" in parts else ()
    )
    months = (
        tuple(int(month) for month in parts["BYMONTH"].split(",")) if "BYMONTH" in parts else ()
    )
    if any(day == 0 or abs(day) > 31 for day in mdays) or any(
        not 1 <= month <= 12 for month in months
    ):
        raise ValueError("Invalid month/day")
    if (
        len(set(days)) != len(days)
        or len(set(mdays)) != len(mdays)
        or len(set(months)) != len(months)
    ):
        raise ValueError("Duplicate recurrence selector")
    if freq == "WEEKLY" and mdays:
        raise ValueError("Weekly BYMONTHDAY unsupported")
    return Rule(freq, interval, count, until, days, mdays, months)


def local_instant(local: datetime, timezone: str) -> datetime | None:
    """RFC profile: nonexistent times omitted; repeated wall time uses first instant."""
    if local.tzinfo is not None:
        raise ValueError("Wall time must have no offset")
    zone = ZoneInfo(timezone)
    aware = local.replace(tzinfo=zone, fold=0)
    utc = aware.astimezone(UTC)
    return utc if utc.astimezone(zone).replace(tzinfo=None) == local else None


def expand(
    local: datetime, timezone: str, rule: Rule, start: datetime, end: datetime
) -> list[datetime]:
    validate_window(start, end)
    if local.year < start.year - 10 or local > end.astimezone(ZoneInfo(timezone)).replace(
        tzinfo=None
    ):
        if local.year < start.year - 10:
            raise ValueError("Recurrence anchor exceeds ten-year bound")
        return []
    zone = ZoneInfo(timezone)
    day = local.date()
    last = end.astimezone(zone).date() + timedelta(days=1)
    count = 0
    results: list[datetime] = []
    for _ in range(4000):
        if day > last:
            return results
        elapsed = (day - local.date()).days
        month_delta = (day.year - local.year) * 12 + day.month - local.month
        if rule.frequency == "DAILY":
            matches = elapsed % rule.interval == 0
        elif rule.frequency == "WEEKLY":
            week = (elapsed + local.weekday()) // 7
            matches = week % rule.interval == 0 and day.weekday() in (
                rule.weekdays or (local.weekday(),)
            )
        elif rule.frequency == "MONTHLY":
            matches = month_delta % rule.interval == 0
            if not rule.monthdays and not rule.weekdays:
                matches = matches and day.day == local.day
        else:
            matches = (day.year - local.year) % rule.interval == 0
            if not rule.months:
                matches = matches and day.month == local.month
            if not rule.monthdays and not rule.weekdays:
                matches = matches and day.day == local.day
        if rule.months:
            matches = matches and day.month in rule.months
        if rule.weekdays:
            matches = matches and day.weekday() in rule.weekdays
        if rule.monthdays:
            maxday = calendar.monthrange(day.year, day.month)[1]
            matches = matches and day.day in tuple(
                d if d > 0 else maxday + d + 1 for d in rule.monthdays
            )
        instant = local_instant(datetime.combine(day, local.time()), timezone) if matches else None
        if instant is not None:
            if rule.until is not None and instant > rule.until:
                return results
            count += 1
            if rule.count is not None and count > rule.count:
                return results
            if start <= instant < end:
                results.append(instant)
                if len(results) > 2000:
                    raise ValueError("Too many occurrences")
        day += timedelta(days=1)
    raise ValueError("Recurrence expansion bound exceeded")


def validate_window(start: datetime, end: datetime) -> None:
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or not timedelta(0) < end - start <= timedelta(days=60)
    ):
        raise ValueError("Window must be aware and between zero and sixty days")


def intervals(anchor: datetime, seconds: int, start: datetime, end: datetime) -> list[datetime]:
    validate_window(start, end)
    if anchor.tzinfo is None or not 3600 <= seconds <= 31536000:
        raise ValueError("Invalid fixed interval")
    offset = max(0, int((start - anchor).total_seconds()) // seconds)
    current = anchor + timedelta(seconds=offset * seconds)
    results: list[datetime] = []
    while current < end:
        if current >= start:
            results.append(current.astimezone(UTC))
        if len(results) > 2000:
            raise ValueError("Too many occurrences")
        current += timedelta(seconds=seconds)
    return results
