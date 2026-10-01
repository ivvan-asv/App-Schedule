from fastapi import APIRouter

from app.api.v1.endpoints import events, health, intents, negotiations, schedule

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(intents.router, prefix="/intents", tags=["Intents"])
api_router.include_router(events.router, prefix="/events", tags=["Events"])
api_router.include_router(schedule.router, prefix="/schedule", tags=["Schedule"])
api_router.include_router(negotiations.router, prefix="/negotiations", tags=["Negotiations"])
