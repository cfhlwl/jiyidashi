from fastapi import APIRouter

from app.api import (
    account_delete,
    annual_memoir,
    auth,
    data_delete,
    data_export,
    family,
    graph,
    intent,
    life_events,
    life_history,
    life_memoir,
    life_stages,
    location,
    long_term_reasoning,
    media,
    memories,
    memory_summaries,
    objects,
    people,
    privacy,
    reminders,
    today_footprint,
    users,
)

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
# [人工注释][S1-022] 账号注销使用独立 durable orchestrator，不复用普通 Profile CRUD。
api_router.include_router(account_delete.router)
api_router.include_router(annual_memoir.router)
api_router.include_router(users.router)
# [人工注释][S1-020] 用户数据导出独立挂载，
# 只读取当前认证用户的权威数据。
api_router.include_router(data_export.router)
# [人工注释][S1-021] 全量数据删除独立走 durable orchestrator；
# 不与普通 CRUD 分散混用。
api_router.include_router(data_delete.router)
# Stage 4A family relationship/permission foundation; membership alone grants no data access.
api_router.include_router(family.router)
# V2-004 is a read-only typed projection over canonical authorities; it owns no data.
api_router.include_router(graph.router)
# S3-003 routing is control metadata only; downstream services retain their own
# trust, Evidence and owner-isolation boundaries.
api_router.include_router(intent.router)
api_router.include_router(memories.router)
# V2-005 is an explicit structured long-term event authority, separate from MemoryType.EVENT.
api_router.include_router(life_events.router)
# V2-009 is a read-only projection over explicit LifeEvent/LifeStage boundaries.
api_router.include_router(life_history.router)
api_router.include_router(life_memoir.router)
api_router.include_router(life_stages.router)
api_router.include_router(long_term_reasoning.router)
# [人工注释][#103] Trusted summaries use a dedicated POST generation surface;
# the legacy GET /memory/summarize/day contract remains untouched.
api_router.include_router(memory_summaries.router)
# [人工注释][S2-012] Today Footprint 只读消费已合并 Timeline/Visit/Place；
# 不建立第二套定位、聚类或持久化协议。
api_router.include_router(today_footprint.router)
# [人工注释][S1-025] Reminder 保持独立资源边界；只引用既有 Memory，不把提醒状态塞进 Memory API。
api_router.include_router(reminders.router)
api_router.include_router(objects.router)
# V2-001 Person is a private self-owned entity surface, separate from accounts/Family.
api_router.include_router(people.router)
api_router.include_router(location.router)
api_router.include_router(privacy.router)
# [人工注释][S1-005][S1-006] A 工作线统一挂载媒体协议；Mini/Flutter 后续只消费
# 这一套 /v1/media 契约，不各自发明上传字段。
api_router.include_router(media.router)
