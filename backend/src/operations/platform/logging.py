import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Do not serialize arbitrary message/exception text or request bodies.
        allowed_events = {
            "http.request.completed",
            "webhook.delivery.completed",
            "webhook.dispatcher.completed",
            "webhook.dispatcher.failed",
        }
        candidate = getattr(record, "event_name", record.getMessage())
        event = candidate if candidate in allowed_events else "operations.event"
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "module": record.name,
                "event": event,
                "request_id": getattr(record, "request_id", None),
                "correlation_id": getattr(record, "correlation_id", None),
                "organization_id": getattr(record, "organization_id", None),
                "actor_id": getattr(record, "actor_id", None),
                "status_code": getattr(record, "status_code", None),
                "duration_ms": getattr(record, "duration_ms", None),
                "trace_id": getattr(record, "trace_id", None),
                "error_code": getattr(record, "error_code", None),
                "delivery_id": getattr(record, "delivery_id", None),
                "attempt": getattr(record, "attempt", None),
                "outcome": getattr(record, "outcome", None),
                "dispatched": getattr(record, "dispatched", None),
            }
        )


def configure_logging() -> None:
    for name in ("operations.http", "operations.webhooks"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(JsonFormatter())
            logger.addHandler(handler)
        logger.propagate = False
