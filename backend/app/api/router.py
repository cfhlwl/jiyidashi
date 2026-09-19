from fastapi import APIRouter

from app.api import (
    account_delete,
    auth,
    data_delete,
    data_export,
    location,
    media,
    memories,
    objects,
    privacy,
    reminders,
    users,
)

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
# [人工注释][S1-022] 账号注销使用独立 durable orchestrator，不复用普通 Profile CRUD。
api_router.include_router(account_delete.router)
api_router.include_router(users.router)
# [人工注释][S1-020] 用户数据导出独立挂载，
# 只读取当前认证用户的权威数据。
api_router.include_router(data_export.router)
# [人工注释][S1-021] 全量数据删除独立走 durable orchestrator；
# 不与普通 CRUD 分散混用。
api_router.include_router(data_delete.router)
api_router.include_router(memories.router)
# [人工注释][S1-025] Reminder 保持独立资源边界；只引用既有 Memory，不把提醒状态塞进 Memory API。
api_router.include_router(reminders.router)
api_router.include_router(objects.router)
api_router.include_router(location.router)
api_router.include_router(privacy.router)
# [人工注释][S1-005][S1-006] A 工作线统一挂载媒体协议；Mini/Flutter 后续只消费
# 这一套 /v1/media 契约，不各自发明上传字段。
api_router.include_router(media.router)
