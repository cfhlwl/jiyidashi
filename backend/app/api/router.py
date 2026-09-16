from fastapi import APIRouter

from app.api import auth, location, media, memories, objects, privacy, users

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(memories.router)
api_router.include_router(objects.router)
api_router.include_router(location.router)
api_router.include_router(privacy.router)
# [人工注释][S1-005][S1-006] 媒体协议由本工作线统一挂载，Mini/Flutter 后续只消费这一套 /v1/media 契约。
api_router.include_router(media.router)
