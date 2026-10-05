import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.propagate import extract
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.platform.health import HealthResponse, InfrastructureProbe, ReadinessProbe
from operations.platform.logging import configure_logging
from operations.platform.telemetry import HttpTelemetry


class ProblemDetails(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    code: str
    request_id: str


def create_app(
    settings: Settings,
    probe: ReadinessProbe | None = None,
    telemetry: HttpTelemetry | None = None,
) -> FastAPI:
    monitoring = telemetry or HttpTelemetry(settings.otlp_endpoint)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        if probe is not None:
            app.state.probe = probe
            try:
                yield
            finally:
                monitoring.close()
            return
        engine = create_database_engine(settings)
        infrastructure: InfrastructureProbe | None = None
        try:
            infrastructure = InfrastructureProbe(engine, settings)
            app.state.probe = infrastructure
            yield
        finally:
            if infrastructure is not None:
                infrastructure.close()
            engine.dispose()
            monitoring.close()

    app = FastAPI(
        title="Industrial Operations Platform",
        version="0.1.0",
        lifespan=lifespan,
        responses={
            code: {"model": ProblemDetails, "content": {"application/problem+json": {}}}
            for code in (404, 422, 500)
        },
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["X-Request-ID", "X-Correlation-ID"],
        expose_headers=["X-Request-ID", "X-Correlation-ID"],
    )

    def identifier(value: str | None) -> str:
        try:
            return str(UUID(value)) if value else str(uuid4())
        except ValueError:
            return str(uuid4())

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = identifier(request.headers.get("X-Request-ID"))
        correlation_id = identifier(request.headers.get("X-Correlation-ID"))
        started = perf_counter()
        with monitoring.tracer.start_as_current_span(
            "http.request",
            context=extract(request.headers),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("request.id", request.state.request_id)
            span.set_attribute("correlation.id", correlation_id)
            try:
                response = await call_next(request)
            except Exception:
                response = problem(request, 500, "Internal server error", "internal_error")
            span.set_attribute("http.response.status_code", response.status_code)
            trace_id = f"{span.get_span_context().trace_id:032x}"
        duration = perf_counter() - started
        monitoring.record(response.status_code, duration)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Correlation-ID"] = correlation_id
        logging.getLogger("operations.http").info(
            "http.request.completed",
            extra={
                "request_id": request.state.request_id,
                "correlation_id": correlation_id,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
                "trace_id": trace_id,
                "error_code": getattr(request.state, "error_code", None),
            },
        )
        return response

    def problem(request: Request, status: int, title: str, code: str) -> JSONResponse:
        request.state.error_code = code
        return JSONResponse(
            status_code=status,
            content=ProblemDetails(
                title=title, status=status, code=code, request_id=request.state.request_id
            ).model_dump(),
            media_type="application/problem+json",
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return problem(request, exc.status_code, "Request failed", "http_error")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem(request, 422, "Request validation failed", "validation_error")

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(content=monitoring.render(), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @app.get("/api/v1/health/live", response_model=HealthResponse, tags=["health"])
    def liveness() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get(
        "/api/v1/health/ready",
        response_model=HealthResponse,
        responses={503: {"model": HealthResponse}},
        tags=["health"],
    )
    def readiness(response: Response, request: Request) -> HealthResponse:
        active_probe: ReadinessProbe = request.app.state.probe
        dependencies = active_probe.check()
        ready = all(value == "up" for value in dependencies.model_dump().values())
        response.status_code = 200 if ready else 503
        return HealthResponse(status="ready" if ready else "unavailable", dependencies=dependencies)

    return app


def app_factory() -> FastAPI:
    return create_app(Settings())  # type: ignore[call-arg]
