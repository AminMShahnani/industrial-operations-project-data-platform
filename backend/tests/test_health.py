import json
import logging
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from operations.main import create_app
from operations.platform.config import Settings
from operations.platform.health import DependencyStatus
from operations.platform.logging import JsonFormatter
from operations.platform.telemetry import HttpTelemetry
from pydantic import SecretStr


class Probe:
    def __init__(self, database: str = "up") -> None:
        self.database = database

    def check(self) -> DependencyStatus:
        return DependencyStatus(
            database="up" if self.database == "up" else "down", redis="up", object_storage="up"
        )


def test_health_and_request_ids(settings: Settings) -> None:
    request_id = str(uuid4())
    with TestClient(create_app(settings, Probe())) as client:
        live = client.get("/api/v1/health/live", headers={"X-Request-ID": request_id})
        assert live.status_code == 200
        assert live.json()["status"] == "ok"
        assert live.headers["X-Request-ID"] == request_id
        UUID(live.headers["X-Correlation-ID"])
        assert client.get("/api/v1/health/ready").json()["status"] == "ready"


def test_liveness_survives_dependency_failure(settings: Settings) -> None:
    with TestClient(create_app(settings, Probe("down"))) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["dependencies"]["database"] == "down"


def test_untrusted_headers_and_errors_are_sanitized(settings: Settings) -> None:
    with TestClient(create_app(settings, Probe())) as client:
        response = client.get("/unknown?secret=private", headers={"X-Request-ID": "bad input"})
        UUID(response.headers["X-Request-ID"])
        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
        assert "private" not in response.text


def test_internal_failure_is_sanitized(settings: Settings) -> None:
    app = create_app(settings, Probe())

    @app.get("/failure")
    def failure() -> None:
        raise RuntimeError("database password: secret-value")

    with TestClient(app) as client:
        response = client.get("/failure")
        assert response.status_code == 500
        assert response.json()["code"] == "internal_error"
        assert "secret-value" not in response.text
        UUID(response.headers["X-Request-ID"])


def test_cors_is_explicit(settings: Settings) -> None:
    with TestClient(create_app(settings, Probe())) as client:
        allowed = client.get("/api/v1/health/live", headers={"Origin": "http://localhost:5173"})
        denied = client.get("/api/v1/health/live", headers={"Origin": "https://untrusted.invalid"})
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert "access-control-allow-origin" not in denied.headers


def test_validation_errors_do_not_echo_inputs(settings: Settings) -> None:
    app = create_app(settings, Probe())

    @app.get("/validate")
    def validate(count: int) -> int:
        return count

    with TestClient(app) as client:
        response = client.get("/validate?count=secret-invalid-input")
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        assert "secret-invalid-input" not in response.text


def test_w3c_trace_context_is_preserved(settings: Settings) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with TestClient(create_app(settings, Probe(), HttpTelemetry(provider=provider))) as client:
        trace_id = "0123456789abcdef0123456789abcdef"
        client.get(
            "/api/v1/health/live",
            headers={"traceparent": f"00-{trace_id}-0123456789abcdef-01"},
        )
        span = exporter.get_finished_spans()[0]
        assert span.context is not None
        assert f"{span.context.trace_id:032x}" == trace_id


def test_structured_logs_do_not_include_arbitrary_secrets() -> None:
    record = logging.LogRecord("operations.http", logging.INFO, "", 0, "secret-value", (), None)
    record.request_id = "request"
    record.status_code = 500
    parsed = json.loads(JsonFormatter().format(record))
    assert parsed["request_id"] == "request"
    assert parsed["status_code"] == 500
    assert "secret-value" not in json.dumps(parsed)


def test_settings_repr_redacts_credentials(settings: Settings) -> None:
    assert "not-a-real-secret" not in repr(settings)
    assert isinstance(settings.database_url, SecretStr)


def test_metrics_and_spans_avoid_unbounded_sensitive_labels(settings: Settings) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry = HttpTelemetry(provider=provider)
    with TestClient(create_app(settings, Probe(), telemetry)) as client:
        client.get("/unknown-secret-path?password=private-value")
        client.get("/api/v1/health/live")
        response = client.get("/metrics")
        assert response.status_code == 200
        assert 'operations_http_requests_total{status_class="4xx"} 1.0' in response.text
        assert "operations_http_request_duration_seconds_bucket" in response.text
        assert "private-value" not in response.text
        assert "unknown-secret-path" not in response.text
        spans = exporter.get_finished_spans()
        assert spans
        assert "private-value" not in str(spans[0].attributes)
        assert not spans[0].events
