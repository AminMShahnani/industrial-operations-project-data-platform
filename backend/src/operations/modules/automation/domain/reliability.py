"""Industry-neutral deterministic retry and causation rules."""

from uuid import UUID, uuid5


def retry_delay(attempt: int, maximum: int = 8) -> int | None:
    if not 1 <= attempt <= maximum <= 20:
        raise ValueError("invalid_retry_attempt")
    return None if attempt == maximum else min(5 * 2 ** (attempt - 1), 3600)


def delivery_id(event_id: UUID, consumer: str) -> UUID:
    if consumer not in {"automation", "notifications"}:
        raise ValueError("unknown_event_consumer")
    return uuid5(event_id, consumer)


def next_causation(path: tuple[UUID, ...], rule_version: UUID) -> tuple[UUID, ...]:
    if len(path) >= 16 or rule_version in path:
        raise ValueError("automation_causation_cycle_or_limit")
    return (*path, rule_version)
