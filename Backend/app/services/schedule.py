from collections.abc import Collection, Sequence
from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgendaRule, Event, Location, User
from app.models.schedule import (
    AgendaRuleType,
    EventOrigin,
    EventStatus,
    EventType,
)
from app.schemas.schedule import AgendaRuleCreate, EventCreate, WorkingHoursReplace


def round_up(moment: datetime, minutes: int) -> datetime:
    step = timedelta(minutes=minutes)
    epoch = datetime(1970, 1, 1, tzinfo=datetime_timezone.utc)
    remainder = (moment - epoch) % step
    return moment if remainder == timedelta(0) else moment + (step - remainder)


def generate_available_slots(
    availability_windows: list[tuple[datetime, datetime]],
    busy_intervals: list[tuple[datetime, datetime]],
    duration_minutes: int,
    step_minutes: int = 15,
) -> list[tuple[datetime, datetime]]:
    if duration_minutes <= 0 or step_minutes <= 0:
        raise ValueError("duration_minutes and step_minutes must be positive")

    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=step_minutes)
    slots: dict[tuple[datetime, datetime], tuple[datetime, datetime]] = {}

    for window_start, window_end in availability_windows:
        if (
            window_start.utcoffset() is None
            or window_end.utcoffset() is None
        ):
            raise ValueError("availability windows must be timezone-aware")
        window_start_utc = window_start.astimezone(datetime_timezone.utc)
        window_end_utc = window_end.astimezone(datetime_timezone.utc)
        if window_end_utc <= window_start_utc:
            continue

        candidate_start_utc = window_start_utc
        while candidate_start_utc + duration <= window_end_utc:
            candidate_end_utc = candidate_start_utc + duration
            has_conflict = any(
                busy_start.astimezone(datetime_timezone.utc) < candidate_end_utc
                and candidate_start_utc < busy_end.astimezone(datetime_timezone.utc)
                for busy_start, busy_end in busy_intervals
            )
            if not has_conflict:
                key = (candidate_start_utc, candidate_end_utc)
                slots[key] = (
                    candidate_start_utc.astimezone(window_start.tzinfo),
                    candidate_end_utc.astimezone(window_start.tzinfo),
                )
            candidate_start_utc += step

    return [slots[key] for key in sorted(slots)]


async def get_active_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    result = await session.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def lock_active_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    """Lock the user row so concurrent writes to the same agenda run serially."""
    result = await session.execute(
        select(User)
        .where(User.id == user_id, User.deleted_at.is_(None))
        .with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def user_timezone(user: User) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"User has an invalid timezone: {user.timezone}",
        ) from error


async def overlaps_agenda(
    session: AsyncSession,
    user_id: uuid.UUID,
    start: datetime,
    end: datetime,
    exclude_event_ids: Collection[uuid.UUID] = (),
) -> bool:
    statement = select(Event.id).where(
        Event.user_id == user_id,
        Event.status.in_([EventStatus.TENTATIVE, EventStatus.CONFIRMED]),
        Event.start < end,
        Event.end > start,
    )
    if exclude_event_ids:
        statement = statement.where(Event.id.not_in(exclude_event_ids))
    overlapping = await session.execute(statement.limit(1))
    return overlapping.scalar_one_or_none() is not None


def overlaps_busy(
    start: datetime,
    end: datetime,
    busy: Sequence[tuple[datetime, datetime]],
) -> bool:
    return any(busy_start < end and start < busy_end for busy_start, busy_end in busy)


async def ensure_no_overlap(
    session: AsyncSession,
    user_id: uuid.UUID,
    start: datetime,
    end: datetime,
    extra_busy: Sequence[tuple[datetime, datetime]] = (),
) -> None:
    if await overlaps_agenda(session, user_id, start, end):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The requested time overlaps an existing event",
        )
    if overlaps_busy(start, end, extra_busy):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The requested time overlaps an event in the device calendar",
        )


async def create_event(
    session: AsyncSession,
    user_id: uuid.UUID,
    event_data: EventCreate,
) -> Event:
    await lock_active_user(session, user_id)

    if event_data.location_id is not None:
        location_result = await session.execute(
            select(Location.id).where(
                Location.id == event_data.location_id,
                Location.user_id == user_id,
            )
        )
        if location_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Location not found for this user",
            )

    await ensure_no_overlap(session, user_id, event_data.start, event_data.end)

    event = Event(
        user_id=user_id,
        title=event_data.title,
        description=event_data.description,
        type=EventType(event_data.type),
        status=EventStatus.CONFIRMED,
        origin=EventOrigin.MANUAL,
        priority=event_data.priority,
        start=event_data.start,
        end=event_data.end,
        location_id=event_data.location_id,
        flexible=event_data.flexible,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def create_working_hours_rule(
    session: AsyncSession,
    user_id: uuid.UUID,
    rule_data: AgendaRuleCreate,
) -> AgendaRule:
    await get_active_user(session, user_id)
    rule = AgendaRule(
        user_id=user_id,
        type=AgendaRuleType.WORKING_HOURS,
        name=rule_data.name,
        weekdays=rule_data.weekdays,
        start_time=rule_data.start_time,
        end_time=rule_data.end_time,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


async def replace_working_hours(
    session: AsyncSession,
    user_id: uuid.UUID,
    schedule: WorkingHoursReplace,
) -> list[AgendaRule]:
    """Replaces the weekly working hours in one transaction."""
    await lock_active_user(session, user_id)
    await session.execute(
        delete(AgendaRule).where(
            AgendaRule.user_id == user_id,
            AgendaRule.type == AgendaRuleType.WORKING_HOURS,
        )
    )
    rules = [
        AgendaRule(
            id=uuid.uuid4(),
            user_id=user_id,
            type=AgendaRuleType.WORKING_HOURS,
            name=rule.name,
            weekdays=rule.weekdays,
            start_time=rule.start_time,
            end_time=rule.end_time,
            active=True,
        )
        for rule in schedule.rules
    ]
    session.add_all(rules)
    await session.commit()
    return sorted(rules, key=lambda rule: (min(rule.weekdays), rule.start_time))


def _working_windows(
    rules: list[AgendaRule],
    timezone: ZoneInfo,
    range_start: datetime,
    range_end: datetime,
) -> list[tuple[datetime, datetime]]:
    first_day = range_start.astimezone(timezone).date()
    last_day = range_end.astimezone(timezone).date()
    windows: list[tuple[datetime, datetime]] = []
    current_day = first_day

    while current_day <= last_day:
        for rule in rules:
            if (
                current_day.isoweekday() not in rule.weekdays
                or rule.start_time is None
                or rule.end_time is None
            ):
                continue
            local_start = datetime.combine(current_day, rule.start_time, tzinfo=timezone)
            local_end = datetime.combine(current_day, rule.end_time, tzinfo=timezone)
            window_start_utc = max(
                local_start.astimezone(datetime_timezone.utc),
                range_start.astimezone(datetime_timezone.utc),
            )
            window_end_utc = min(
                local_end.astimezone(datetime_timezone.utc),
                range_end.astimezone(datetime_timezone.utc),
            )
            window_start = window_start_utc.astimezone(timezone)
            window_end = window_end_utc.astimezone(timezone)
            if window_start_utc < window_end_utc:
                windows.append((window_start, window_end))
        current_day += timedelta(days=1)

    return windows


async def find_available_slots(
    session: AsyncSession,
    user_id: uuid.UUID,
    range_start: datetime,
    range_end: datetime,
    duration_minutes: int,
    step_minutes: int,
    extra_busy: Sequence[tuple[datetime, datetime]] = (),
    exclude_event_ids: Collection[uuid.UUID] = (),
) -> list[tuple[datetime, datetime]]:
    """Free slots inside working hours, avoiding agenda events and `extra_busy`.

    Events in `exclude_event_ids` do not count as busy, so an event that is
    being moved does not block its own new time.
    """
    if range_start.utcoffset() is None or range_end.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from and to must include a timezone",
        )
    if range_end <= range_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="to must be later than from",
        )
    if duration_minutes <= 0 or step_minutes <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="duration_minutes and step_minutes must be positive",
        )

    user = await get_active_user(session, user_id)
    timezone = user_timezone(user)

    rules_result = await session.execute(
        select(AgendaRule).where(
            AgendaRule.user_id == user_id,
            AgendaRule.type == AgendaRuleType.WORKING_HOURS,
            AgendaRule.active.is_(True),
        )
    )
    rules = list(rules_result.scalars().all())
    if not rules:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active working-hours rules are configured",
        )

    events_statement = select(Event).where(
        Event.user_id == user_id,
        Event.status.in_([EventStatus.TENTATIVE, EventStatus.CONFIRMED]),
        Event.start < range_end,
        Event.end > range_start,
    )
    if exclude_event_ids:
        events_statement = events_statement.where(Event.id.not_in(exclude_event_ids))
    events_result = await session.execute(events_statement)
    busy_intervals = [
        (event.start, event.end) for event in events_result.scalars().all()
    ]
    busy_intervals.extend(extra_busy)
    windows = _working_windows(rules, timezone, range_start, range_end)
    return generate_available_slots(
        windows,
        busy_intervals,
        duration_minutes,
        step_minutes,
    )
