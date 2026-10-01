from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import CalendarEvent, User


class LocalCalendarProvider:
    provider_name = "local"

    async def list_busy(
        self, session: AsyncSession, user_id: UUID, window_start: datetime, window_end: datetime
    ) -> list[tuple[datetime, datetime]]:
        result = await session.execute(
            select(CalendarEvent).where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.status != "cancelled",
                CalendarEvent.start_time < window_end,
                CalendarEvent.end_time > window_start,
            )
        )
        events = result.scalars().all()
        return [(event.start_time, event.end_time) for event in events]

    async def commit(self, event: CalendarEvent) -> str:
        return f"local:{event.id}"


class GoogleCalendarProvider:
    provider_name = "google"

    async def commit(self, event: CalendarEvent) -> str:
        raise NotImplementedError("Google Calendar v3 se conecta en la Fase 2")


class OutlookCalendarProvider:
    provider_name = "outlook"

    async def commit(self, event: CalendarEvent) -> str:
        raise NotImplementedError("Microsoft Graph se conecta en la Fase 2")


def get_calendar_provider(name: str = "local"):
    if name == "google":
        return GoogleCalendarProvider()
    if name == "outlook":
        return OutlookCalendarProvider()
    return LocalCalendarProvider()


async def get_or_create_demo_user(session: AsyncSession) -> User:
    from app.core.config import settings

    result = await session.execute(select(User).where(User.email == settings.DEMO_USER_EMAIL))
    user = result.scalar_one_or_none()
    if user:
        return user
    user = User(
        email=settings.DEMO_USER_EMAIL,
        name="Demo User",
        timezone=settings.DEMO_USER_TIMEZONE,
    )
    session.add(user)
    await session.flush()
    return user
