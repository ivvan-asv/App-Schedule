from fastapi import APIRouter

from app.api.v1.users import router as users_router

api_router = APIRouter()
api_router.include_router(users_router)


@api_router.get("/health", tags=["Health"])
async def api_health() -> dict[str, str]:
    return {"status": "healthy"}
