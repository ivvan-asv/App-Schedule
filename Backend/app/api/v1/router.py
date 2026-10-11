from fastapi import APIRouter

from app.api.v1.user import router as user_router

api_router = APIRouter()
api_router.include_router(user_router)


@api_router.get("/health", tags=["Health"])
async def api_health() -> dict[str, str]:
    return {"status": "healthy"}
