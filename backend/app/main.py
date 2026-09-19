from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.db import UserDataRequestStale, create_schema

settings = get_settings()


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
