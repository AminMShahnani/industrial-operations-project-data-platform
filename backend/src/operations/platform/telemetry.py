from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest


class HttpTelemetry:
    def __init__(self, endpoint: str | None = None, provider: TracerProvider | None = None) -> None:
        self.provider = provider or TracerProvider(
            resource=Resource.create({"service.name": "industrial-operations-api"})
        )
        if endpoint:
            self.provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=3))
            )
        self.tracer: trace.Tracer = self.provider.get_tracer("operations.http")
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "operations_http_requests_total",
            "Completed HTTP requests",
            ["status_class"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "operations_http_request_duration_seconds",
            "HTTP request duration",
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 1, 2, 5),
            registry=self.registry,
        )

    def record(self, status: int, duration: float) -> None:
        self.requests.labels(status_class=f"{status // 100}xx").inc()
        self.latency.observe(duration)

    def render(self) -> bytes:
        return generate_latest(self.registry)

    def close(self) -> None:
        self.provider.shutdown()
