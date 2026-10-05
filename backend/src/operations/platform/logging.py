import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Do not serialize arbitrary message/exception text or request bodies.
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "module": record.name,
                "event": "http.request.completed",
                "request_id": getattr(record, "request_id", None),
                "correlation_id": getattr(record, "correlation_id", None),
                "organization_id": getattr(record, "organization_id", None),
                "actor_id": getattr(record, "actor_id", None),
                "status_code": getattr(record, "status_code", None),
                "duration_ms": getattr(record, "duration_ms", None),
                "trace_id": getattr(record, "trace_id", None),
                "error_code": getattr(record, "error_code", None),
            }
        )


def configure_logging() -> None:
    logger = logging.getLogger("operations.http")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.propagate = False
