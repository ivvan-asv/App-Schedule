from fastapi import APIRouter

from app.api.v1.capture import router as capture_router
from app.api.v1.schedule import router as schedule_router
from app.api.v1.user import router as user_router

api_router = APIRouter()
api_router.include_router(user_router)
api_router.include_router(schedule_router)
api_router.include_router(capture_router)


@api_router.get("/health", tags=["Health"])
async def api_health() -> dict[str, str]:
    return {"status": "healthy"}
