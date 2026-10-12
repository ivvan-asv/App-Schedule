from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import AgendaRule, Event
from app.schemas.schedule import (
    AgendaRuleCreate,
    AgendaRuleRead,
    AvailableSlot,
    EventCreate,
    EventRead,
)
from app.services.schedule import (
    create_event,
    create_working_hours_rule,
    find_available_slots,
    get_active_user,
)

router = APIRouter(prefix="/users/{user_id}", tags=["Scheduling"])


@router.post("/events", response_model=EventRead, status_code=201)
async def post_event(
    user_id: uuid.UUID,
    event_data: EventCreate,
    session: AsyncSession = Depends(get_db),
) -> EventRead:
    return await create_event(session, user_id, event_data)


@router.get("/events", response_model=list[EventRead])
async def list_events(
    user_id: uuid.UUID,
    from_: datetime = Query(alias="from"),
    to: datetime = Query(),
    session: AsyncSession = Depends(get_db),
) -> list[Event]:
    if from_.utcoffset() is None or to.utcoffset() is None or to <= from_:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from and to must be timezone-aware and to must be later than from",
        )

    await get_active_user(session, user_id)
    result = await session.execute(
        select(Event)
        .where(
            Event.user_id == user_id,
            Event.start < to,
            Event.end > from_,
        )
        .order_by(Event.start)
    )
    return list(result.scalars().all())


@router.post("/availability-rules", response_model=AgendaRuleRead, status_code=201)
async def post_availability_rule(
    user_id: uuid.UUID,
    rule_data: AgendaRuleCreate,
    session: AsyncSession = Depends(get_db),
) -> AgendaRuleRead:
    return await create_working_hours_rule(session, user_id, rule_data)


@router.get("/availability-rules", response_model=list[AgendaRuleRead])
async def list_availability_rules(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> list[AgendaRule]:
    await get_active_user(session, user_id)
    result = await session.execute(
        select(AgendaRule)
        .where(AgendaRule.user_id == user_id, AgendaRule.active.is_(True))
        .order_by(AgendaRule.start_time)
    )
    return list(result.scalars().all())


@router.get("/availability/slots", response_model=list[AvailableSlot])
async def get_available_slots(
    user_id: uuid.UUID,
    from_: datetime = Query(alias="from"),
    to: datetime = Query(),
    duration_minutes: int = Query(gt=0, le=1440),
    step_minutes: int = Query(default=15, gt=0, le=1440),
    session: AsyncSession = Depends(get_db),
) -> list[AvailableSlot]:
    slots = await find_available_slots(
        session,
        user_id,
        from_,
        to,
        duration_minutes,
        step_minutes,
    )
    return [AvailableSlot(start=start, end=end) for start, end in slots]
