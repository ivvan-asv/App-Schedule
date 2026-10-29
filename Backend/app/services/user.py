import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas.user import UserUpdate
from app.services.schedule import lock_active_user

DEMO_USER_EMAIL = "demo@smart-scheduler.local"


async def get_or_create_demo_user(session: AsyncSession) -> User:
    result = await session.execute(select(User).where(User.email == DEMO_USER_EMAIL))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    user = User(email=DEMO_USER_EMAIL, display_name="Demo User")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    user_data: UserUpdate,
) -> User:
    user = await lock_active_user(session, user_id)
    changes = user_data.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(user, field, value)
    if changes:
        user.updated_at = func.now()
    await session.commit()
    await session.refresh(user)
    return user
