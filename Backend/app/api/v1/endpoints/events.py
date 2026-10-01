from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.entities import CalendarEvent
from app.schemas.event import EventCreateRequest, EventRead
from app.services.calendar import get_calendar_provider, get_or_create_demo_user

router = APIRouter()


@router.get("", response_model=list[EventRead])
async def list_events(session: AsyncSession = Depends(get_db)) -> list[CalendarEvent]:
    user = await get_or_create_demo_user(session)
    result = await session.execute(
        select(CalendarEvent)
        .where(CalendarEvent.user_id == user.id, CalendarEvent.status != "cancelled")
        .order_by(CalendarEvent.start_time.asc())
    )
    return list(result.scalars().all())


@router.post("", response_model=EventRead)
async def create_event(
    payload: EventCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> CalendarEvent:
    user = await get_or_create_demo_user(session)
    end_time = payload.start_time + timedelta(minutes=payload.duration_minutes)
    event = CalendarEvent(
        user_id=user.id,
        title=payload.title,
        start_time=payload.start_time,
        end_time=end_time,
        location=payload.location,
        priority=payload.priority,
        notes=payload.notes,
        attendees=payload.attendees,
        travel_before_minutes=payload.travel_before_minutes,
        travel_after_minutes=payload.travel_after_minutes,
        source_text=payload.source_text,
        status="confirmed" if payload.commit_to_calendar else "draft",
        calendar_provider="local",
    )
    session.add(event)
    await session.flush()
    if payload.commit_to_calendar:
        provider = get_calendar_provider("local")
        event.external_id = await provider.commit(event)
    return event


@router.delete("/{event_id}", response_model=EventRead)
async def cancel_event(event_id: UUID, session: AsyncSession = Depends(get_db)) -> CalendarEvent:
    event = await session.get(CalendarEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    event.status = "cancelled"
    await session.flush()
    return event
