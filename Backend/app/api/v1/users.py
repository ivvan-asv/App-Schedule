from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.user import UserRead
from app.services.users import get_or_create_demo_user

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/demo", response_model=UserRead)
async def create_demo_user(
    session: AsyncSession = Depends(get_db),
) -> UserRead:
    return await get_or_create_demo_user(session)
