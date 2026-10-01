from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.redis import get_redis

router = APIRouter()


@router.get("/health")
async def health_check(
    session: AsyncSession = Depends(get_db),
    cache: aioredis.Redis = Depends(get_redis),
):
    db_ok = True
    redis_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    try:
        await cache.ping()
    except Exception:
        redis_ok = False
    status = "healthy" if db_ok and redis_ok else "degraded"
    return {
        "status": status,
        "database": db_ok,
        "redis": redis_ok,
    }
