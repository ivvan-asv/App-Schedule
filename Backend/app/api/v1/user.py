import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.user import UserRead, UserUpdate
from app.services.user import get_or_create_demo_user, update_user

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/demo", response_model=UserRead)
async def create_demo_user(
    session: AsyncSession = Depends(get_db),
) -> UserRead:
    return await get_or_create_demo_user(session)


@router.patch("/{user_id}", response_model=UserRead)
async def patch_user(
    user_id: uuid.UUID,
    user_data: UserUpdate,
    session: AsyncSession = Depends(get_db),
) -> UserRead:
    return await update_user(session, user_id, user_data)
