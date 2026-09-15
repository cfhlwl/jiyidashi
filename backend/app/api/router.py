from fastapi import APIRouter

from app.api import auth, location, memories, objects, privacy

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(memories.router)
api_router.include_router(objects.router)
api_router.include_router(location.router)
api_router.include_router(privacy.router)
