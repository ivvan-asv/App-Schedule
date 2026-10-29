"""Saved places and travel blocks before events (RF04).

Travel times are estimated by the app with the device's map service (MapKit)
and sent here; the backend stores the place, inserts the travel block and,
when the trip does not fit, moves flexible events.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import math
import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Location, Travel
from app.models.schedule import EventStatus, EventType
from app.schemas.schedule import EventLocationUpdate, LocationCreate
from app.services.schedule import (
    find_available_slots,
    get_active_user,
    lock_active_user,
    overlaps_agenda,
    overlaps_busy,
    round_up,
)

SLOT_STEP_MINUTES = 15
TRAVEL_ROUNDING_MINUTES = 5
DEFAULT_SEARCH_HORIZON = timedelta(days=7)
# Shorter trips (same building, next door) get no travel block.
MIN_TRAVEL_SECONDS = 60


@dataclass(frozen=True)
class EventLocationOutcome:
    event: Event
    location: Location
    travel: Event | None
    moved: bool
    travel_overlaps: bool


def travel_block_duration(seconds: int) -> timedelta | None:
    """Rounds a trip up to whole 5-minute steps, so the block has some slack."""
    if seconds < MIN_TRAVEL_SECONDS:
        return None
    minutes = math.ceil(seconds / 60 / TRAVEL_ROUNDING_MINUTES) * TRAVEL_ROUNDING_MINUTES
    return timedelta(minutes=minutes)


def _coordinate(value: float) -> Decimal:
    # Matches the NUMERIC(9,6) columns, so equal coordinates compare equal.
    return Decimal(str(round(value, 6)))


async def list_locations(session: AsyncSession, user_id: uuid.UUID) -> list[Location]:
    await get_active_user(session, user_id)
    result = await session.execute(
        select(Location)
        .where(Location.user_id == user_id)
        .order_by(Location.is_frequent.desc(), Location.alias, Location.created_at)
    )
    return list(result.scalars().all())


async def save_location(
    session: AsyncSession,
    user_id: uuid.UUID,
    data: LocationCreate,
) -> Location:
    """Saves a place. A place with the same alias ("Casa") is moved instead of duplicated."""
    await lock_active_user(session, user_id)
    location = None
    if data.alias:
        result = await session.execute(
            select(Location).where(
                Location.user_id == user_id,
                func.lower(Location.alias) == data.alias.strip().lower(),
            )
        )
        location = result.scalars().first()
    if location is None:
        location = Location(user_id=user_id)
        session.add(location)

    location.alias = data.alias.strip() if data.alias else None
    location.address = data.address
    location.latitude = _coordinate(data.latitude)
    location.longitude = _coordinate(data.longitude)
    location.place_id = data.place_id
    location.is_frequent = data.is_frequent
    await session.commit()
    await session.refresh(location)
    return location


async def delete_location(
    session: AsyncSession,
    user_id: uuid.UUID,
    location_id: uuid.UUID,
) -> None:
    location = await _user_location(session, user_id, location_id)
    await session.delete(location)
    await session.commit()


async def _user_location(
    session: AsyncSession,
    user_id: uuid.UUID,
    location_id: uuid.UUID,
) -> Location:
    result = await session.execute(
        select(Location).where(Location.id == location_id, Location.user_id == user_id)
    )
    location = result.scalar_one_or_none()
    if location is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location not found for this user",
        )
    return location


async def _resolve_destination(
    session: AsyncSession,
    user_id: uuid.UUID,
    update: EventLocationUpdate,
) -> Location:
    if update.location_id is not None:
        return await _user_location(session, user_id, update.location_id)

    data = update.location
    assert data is not None  # guaranteed by EventLocationUpdate
    same_coordinates = (Location.latitude == _coordinate(data.latitude)) & (
        Location.longitude == _coordinate(data.longitude)
    )
    same_place = same_coordinates
    if data.place_id:
        same_place = or_(Location.place_id == data.place_id, same_coordinates)
    result = await session.execute(
        select(Location).where(Location.user_id == user_id, same_place).limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    location = Location(
        id=uuid.uuid4(),
        user_id=user_id,
        alias=data.alias,
        address=data.address,
        latitude=_coordinate(data.latitude),
        longitude=_coordinate(data.longitude),
        place_id=data.place_id,
        is_frequent=data.is_frequent,
    )
    session.add(location)
    await session.flush()
    return location


async def _first_start_with_travel(
    session: AsyncSession,
    user_id: uuid.UUID,
    event: Event,
    travel: timedelta,
    busy: list[tuple[datetime, datetime]],
) -> datetime | None:
    """Earliest event start, inside its window, with room for the trip before it."""
    now = datetime.now(UTC)
    range_start = round_up(max(event.window_start or now, now), SLOT_STEP_MINUTES)
    range_end = event.window_end or range_start + DEFAULT_SEARCH_HORIZON
    if range_end <= range_start:
        return None

    total_minutes = math.ceil((event.end - event.start + travel).total_seconds() / 60)
    try:
        slots = await find_available_slots(
            session,
            user_id,
            range_start,
            range_end,
            total_minutes,
            SLOT_STEP_MINUTES,
            busy,
            exclude_event_ids={event.id},
        )
    except HTTPException:
        # No working-hours rules: there is nowhere to move the event.
        return None
    return slots[0][0] + travel if slots else None


async def set_event_location(
    session: AsyncSession,
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    update: EventLocationUpdate,
) -> EventLocationOutcome:
    """Sets where an event happens and inserts the travel block before it.

    Calling it again replaces the previous travel block, so retries are safe.
    """
    await lock_active_user(session, user_id)
    result = await session.execute(
        select(Event).where(
            Event.id == event_id,
            Event.user_id == user_id,
            Event.type.in_([EventType.TASK, EventType.MEETING]),
            Event.status != EventStatus.CANCELLED,
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    destination = await _resolve_destination(session, user_id, update)
    if update.travel is not None and update.travel.origin_location_id is not None:
        await _user_location(session, user_id, update.travel.origin_location_id)

    event.location_id = destination.id
    await session.execute(
        delete(Event).where(Event.parent_id == event.id, Event.type == EventType.TRAVEL)
    )

    travel_event = None
    moved = False
    travel_overlaps = False
    block = travel_block_duration(update.travel.duration_seconds) if update.travel else None
    if update.travel is not None and block is not None:
        busy = [(interval.start, interval.end) for interval in update.busy_intervals]
        travel_start = event.start - block
        if await overlaps_agenda(
            session, user_id, travel_start, event.start, {event.id}
        ) or overlaps_busy(travel_start, event.start, busy):
            new_start = None
            if event.flexible:
                new_start = await _first_start_with_travel(session, user_id, event, block, busy)
            if new_start is None:
                travel_overlaps = True
            else:
                duration = event.end - event.start
                event.start = new_start
                event.end = new_start + duration
                moved = True

        name = destination.alias or destination.address or "destino"
        travel_event = Event(
            id=uuid.uuid4(),
            user_id=user_id,
            parent_id=event.id,
            title=f"Traslado a {name}"[:255],
            type=EventType.TRAVEL,
            status=event.status,
            origin=event.origin,
            priority=event.priority,
            start=event.start - block,
            end=event.start,
        )
        session.add(travel_event)
        await session.flush()
        session.add(
            Travel(
                event_id=travel_event.id,
                origin_id=update.travel.origin_location_id,
                destination_id=destination.id,
                mode=update.travel.mode,
                duration_seconds=update.travel.duration_seconds,
                distance_meters=update.travel.distance_meters,
                provider=update.travel.provider,
            )
        )

    event.updated_at = func.now()
    await session.commit()
    await session.refresh(event)
    return EventLocationOutcome(
        event=event,
        location=destination,
        travel=travel_event,
        moved=moved,
        travel_overlaps=travel_overlaps,
    )
