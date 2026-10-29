import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Location
from app.schemas.schedule import (
    EventLocationRead,
    EventLocationUpdate,
    EventRead,
    LocationCreate,
    LocationRead,
)
from app.services.location import (
    delete_location,
    list_locations,
    save_location,
    set_event_location,
)

router = APIRouter(prefix="/users/{user_id}", tags=["Locations"])


@router.get("/locations", response_model=list[LocationRead])
async def get_locations(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> list[Location]:
    return await list_locations(session, user_id)


@router.post("/locations", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
async def post_location(
    user_id: uuid.UUID,
    location_data: LocationCreate,
    session: AsyncSession = Depends(get_db),
) -> Location:
    return await save_location(session, user_id, location_data)


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_location(
    user_id: uuid.UUID,
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> Response:
    await delete_location(session, user_id, location_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/events/{event_id}/location", response_model=EventLocationRead)
async def put_event_location(
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    update: EventLocationUpdate,
    session: AsyncSession = Depends(get_db),
) -> EventLocationRead:
    outcome = await set_event_location(session, user_id, event_id, update)
    return EventLocationRead(
        event=EventRead.model_validate(outcome.event),
        location=LocationRead.model_validate(outcome.location),
        travel=EventRead.model_validate(outcome.travel) if outcome.travel else None,
        moved=outcome.moved,
        travel_overlaps=outcome.travel_overlaps,
    )
