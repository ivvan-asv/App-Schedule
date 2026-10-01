from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.engine.csp import find_optimal_slot
from app.engine.travel import estimate_travel_minutes
from app.schemas.event import OptimizeRequest, OptimizeResponse
from app.services.calendar import LocalCalendarProvider, get_or_create_demo_user

router = APIRouter()


@router.post("/optimize", response_model=OptimizeResponse)
async def optimize_slot(
    payload: OptimizeRequest,
    session: AsyncSession = Depends(get_db),
) -> OptimizeResponse:
    user = await get_or_create_demo_user(session)
    travel = await estimate_travel_minutes(payload.origin_location, payload.location)
    provider = LocalCalendarProvider()
    busy = await provider.list_busy(session, user.id, payload.window_start, payload.window_end)
    suggested, solver = find_optimal_slot(
        busy=busy,
        duration_minutes=payload.duration_minutes,
        window_start=payload.window_start,
        window_end=payload.window_end,
        travel_before=travel,
        travel_after=0,
    )
    if not suggested:
        raise HTTPException(status_code=409, detail="No hay un hueco disponible en esa ventana")
    return OptimizeResponse(
        suggested_start=suggested,
        duration_minutes=payload.duration_minutes,
        travel_before_minutes=travel,
        solver=solver,
    )
