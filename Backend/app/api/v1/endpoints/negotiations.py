from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.event import (
    EventCreateRequest,
    EventRead,
    NegotiationConfirmRequest,
    NegotiationCreateRequest,
    NegotiationRead,
)
from app.services.calendar import get_or_create_demo_user
from app.services.messaging import create_negotiation, get_negotiation_by_token
from app.api.v1.endpoints.events import create_event

router = APIRouter()


def _to_read(negotiation, confirm_base: str = "http://localhost:3000") -> NegotiationRead:
    starts = [datetime.fromisoformat(item) if isinstance(item, str) else item for item in negotiation.proposed_starts]
    return NegotiationRead(
        id=negotiation.id,
        public_token=negotiation.public_token,
        title=negotiation.title,
        recipient=negotiation.recipient,
        channel=negotiation.channel,
        proposed_starts=starts,
        status=negotiation.status,
        confirm_url=f"{confirm_base}/confirm/{negotiation.public_token}",
    )


@router.post("", response_model=NegotiationRead)
async def start_negotiation(
    payload: NegotiationCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> NegotiationRead:
    user = await get_or_create_demo_user(session)
    negotiation = await create_negotiation(
        session=session,
        user_id=user.id,
        title=payload.title,
        duration_minutes=payload.duration_minutes,
        recipient=payload.recipient,
        channel=payload.channel,
        proposed_starts=payload.proposed_starts,
        event_id=payload.event_id,
    )
    return _to_read(negotiation)


@router.get("/{token}", response_model=NegotiationRead)
async def read_negotiation(token: str, session: AsyncSession = Depends(get_db)) -> NegotiationRead:
    negotiation = await get_negotiation_by_token(session, token)
    if not negotiation:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")
    return _to_read(negotiation)


@router.post("/confirm", response_model=EventRead)
async def confirm_negotiation(
    payload: NegotiationConfirmRequest,
    session: AsyncSession = Depends(get_db),
) -> EventRead:
    negotiation = await get_negotiation_by_token(session, payload.token)
    if not negotiation:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")
    if negotiation.status != "pending":
        raise HTTPException(status_code=409, detail="La invitación ya fue resuelta")

    starts = [
        datetime.fromisoformat(item) if isinstance(item, str) else item
        for item in negotiation.proposed_starts
    ]
    selected = payload.selected_start
    if selected.tzinfo is None and starts and starts[0].tzinfo is not None:
        selected = selected.replace(tzinfo=starts[0].tzinfo)
    if all(selected != item for item in starts):
        raise HTTPException(status_code=400, detail="El horario elegido no está entre las opciones")

    event = await create_event(
        EventCreateRequest(
            title=negotiation.title,
            start_time=payload.selected_start,
            duration_minutes=negotiation.duration_minutes,
            notes=f"Confirmado por {negotiation.recipient} vía {negotiation.channel}",
            commit_to_calendar=True,
        ),
        session,
    )
    negotiation.status = "accepted"
    negotiation.event_id = event.id
    await session.flush()
    return event
