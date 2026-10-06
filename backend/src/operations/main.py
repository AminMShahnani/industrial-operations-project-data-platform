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
from redis import Redis
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException

from operations.api import router
from operations.contracts import ServiceError
from operations.modules.identity.application.contracts import TokenVerifier
from operations.modules.identity.infrastructure.oidc import OidcVerifier
from operations.phase2_api import router as phase2_router
from operations.phase3_api import router as phase3_router
from operations.phase4_api import router as phase4_router
from operations.phase5_api import router as phase5_router
from operations.platform.body_limit import RequestBodyLimit
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.platform.health import HealthResponse, InfrastructureProbe, ReadinessProbe
from operations.platform.logging import configure_logging
from operations.platform.rate_limit import RequestLimiter
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
    verifier: TokenVerifier | None = None,
) -> FastAPI:
    monitoring = telemetry or HttpTelemetry(settings.otlp_endpoint)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        engine = create_database_engine(settings)
        app.state.sessions = sessionmaker(engine, expire_on_commit=False)
        app.state.verifier = verifier or OidcVerifier(settings)
        rate_redis = Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_timeout=2,
            socket_connect_timeout=2,
        )
        app.state.limiter = RequestLimiter(rate_redis, settings.api_rate_limit)
        infrastructure: InfrastructureProbe | None = None
        try:
            if probe is None:
                infrastructure = InfrastructureProbe(engine, settings)
                app.state.probe = infrastructure
            else:
                app.state.probe = probe
            yield
        finally:
            if infrastructure is not None:
                infrastructure.close()
            engine.dispose()
            rate_redis.close()
            monitoring.close()

    app = FastAPI(
        title="Industrial Operations Platform",
        version="0.1.0",
        lifespan=lifespan,
        responses={
            code: {"model": ProblemDetails, "content": {"application/problem+json": {}}}
            for code in (401, 403, 404, 409, 413, 422, 429, 500, 503)
        },
    )
    app.state.settings = settings
    app.add_middleware(RequestBodyLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Correlation-ID"],
        expose_headers=["X-Request-ID", "X-Correlation-ID", "X-Next-Cursor", "Content-Disposition"],
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
        request.state.correlation_id = correlation_id
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
                "organization_id": getattr(request.state, "organization_id", None),
                "actor_id": getattr(request.state, "actor_id", None),
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

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:
        response = problem(request, exc.status, "Request failed", exc.code)
        if exc.status == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        if exc.status == 429:
            response.headers["Retry-After"] = "60"
        return response

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

    app.include_router(router)
    app.include_router(phase2_router)
    app.include_router(phase3_router)
    app.include_router(phase4_router)
    app.include_router(phase5_router)
    return app


def app_factory() -> FastAPI:
    return create_app(Settings())  # type: ignore[call-arg]
