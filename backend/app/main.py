from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import get_settings
from app.core.db import UserDataRequestStale, create_schema, engine, readiness_engine
from app.core.observability import (
    configure_observability_log_level,
    emit_operational_event,
    normalize_request_id,
    reset_request_id,
    set_request_id,
)

settings = get_settings()
configure_observability_log_level(settings.observability_log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        create_schema()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if not isinstance(path, str) or not path:
        return "__unmatched__"

    # Included FastAPI routers can expose their local template through scope["route"].
    # Re-attach only the repository-owned static API prefix; raw request paths are never
    # serialized into telemetry and are used here only for a boolean prefix check.
    api_prefix = api_router.prefix
    raw_path = request.scope.get("path")
    if (
        api_prefix
        and not path.startswith(api_prefix)
        and isinstance(raw_path, str)
        and (raw_path == api_prefix or raw_path.startswith(f"{api_prefix}/"))
    ):
        return f"{api_prefix}{path}"
    return path


@app.middleware("http")
async def request_correlation_and_telemetry(request: Request, call_next):
    request_id = normalize_request_id(request.headers.get("X-Request-ID"))
    token = set_request_id(request_id)
    started = perf_counter()
    try:
        try:
            response = await call_next(request)
        except Exception:
            emit_operational_event(
                event="http.request.failed",
                level="ERROR",
                request_id=request_id,
                method=request.method,
                route=_route_template(request),
                status_code=500,
                latency_ms=(perf_counter() - started) * 1000,
                error_code="UNHANDLED_EXCEPTION",
            )
            raise

        response.headers["X-Request-ID"] = request_id
        route = _route_template(request)
        level = "DEBUG" if route in {"/health", "/health/ready"} else "INFO"
        emit_operational_event(
            event="http.request.completed",
            level=level,
            request_id=request_id,
            method=request.method,
            route=route,
            status_code=response.status_code,
            latency_ms=(perf_counter() - started) * 1000,
        )
        return response
    finally:
        reset_request_id(token)


@app.exception_handler(UserDataRequestStale)
async def stale_user_data_request_handler(
    _: Request,
    exc: UserDataRequestStale,
) -> JSONResponse:
    # [人工注释][S1-021-FIX-001] 旧请求在删除 generation 变化后只能失败关闭；
    # 409 区分“旧请求已失效”与当前仍在执行删除时入口返回的 423。
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "jiyidashi-backend",
    }


@app.get("/health/ready", response_model=None)
def readiness() -> JSONResponse:
    try:
        with readiness_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        emit_operational_event(
            event="dependency.readiness",
            level="WARNING",
            dependency="database",
            ready=False,
            error_code="DATABASE_UNAVAILABLE",
        )
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "unavailable"},
        )

    emit_operational_event(
        event="dependency.readiness",
        level="DEBUG",
        dependency="database",
        ready=True,
    )
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "database": "ready"},
    )
