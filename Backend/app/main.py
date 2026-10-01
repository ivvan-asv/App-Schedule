from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal
from app.core.redis import redis_pool
from app.models import CalendarAccount, CalendarEvent, Negotiation, User  # noqa: F401
from app.services.calendar import get_or_create_demo_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await get_or_create_demo_user(session)
        await session.commit()
    yield
    await redis_pool.disconnect()
    await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["Health"])
async def root():
    return {"service": settings.PROJECT_NAME, "docs": "/docs"}


@app.get("/health", tags=["Health"])
async def root_health():
    return {"status": "healthy", "service": settings.PROJECT_NAME}
