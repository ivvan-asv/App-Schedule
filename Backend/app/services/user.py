from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

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
