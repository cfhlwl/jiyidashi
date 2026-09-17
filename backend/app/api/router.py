from fastapi import APIRouter

from app.api import auth, data_export, location, media, memories, objects, privacy, users

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
# [人工注释][S1-020] 用户数据导出独立挂载，只读取当前认证用户的权威数据。
api_router.include_router(data_export.router)
api_router.include_router(memories.router)
api_router.include_router(objects.router)
api_router.include_router(location.router)
api_router.include_router(privacy.router)
# [人工注释][S1-005][S1-006] A 工作线统一挂载媒体协议；Mini/Flutter 后续只消费
# 这一套 /v1/media 契约，不各自发明上传字段。
api_router.include_router(media.router)