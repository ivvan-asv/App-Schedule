import secrets
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Negotiation


async def create_negotiation(
    session: AsyncSession,
    user_id: UUID,
    title: str,
    duration_minutes: int,
    recipient: str,
    channel: str,
    proposed_starts: list[datetime],
    event_id: UUID | None = None,
) -> Negotiation:
    negotiation = Negotiation(
        id=uuid4(),
        user_id=user_id,
        event_id=event_id,
        public_token=secrets.token_urlsafe(24),
        title=title,
        duration_minutes=duration_minutes,
        recipient=recipient,
        channel=channel,
        proposed_starts=[item.isoformat() for item in proposed_starts],
        status="pending",
    )
    session.add(negotiation)
    await session.flush()
    return negotiation


async def get_negotiation_by_token(session: AsyncSession, token: str) -> Negotiation | None:
    result = await session.execute(select(Negotiation).where(Negotiation.public_token == token))
    return result.scalar_one_or_none()
