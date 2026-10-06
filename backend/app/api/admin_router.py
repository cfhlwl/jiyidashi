from fastapi import APIRouter

from app.api import (
    admin_accounts,
    admin_auth,
    notifications_admin,
    admin_operations,
    admin_provider_settings,
    admin_settings,
)

admin_api_router = APIRouter(prefix="/admin/api/v1")
admin_api_router.include_router(admin_auth.router)
admin_api_router.include_router(admin_accounts.router)
admin_api_router.include_router(admin_settings.router)
admin_api_router.include_router(admin_provider_settings.router)
admin_api_router.include_router(notifications_admin.router)
admin_api_router.include_router(admin_operations.router)
