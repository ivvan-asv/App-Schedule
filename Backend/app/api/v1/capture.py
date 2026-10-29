import uuid

from fastapi import APIRouter, Depends, Response, status
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.capture import CaptureCreate, CaptureRead
from app.schemas.schedule import EventRead
from app.services.calendar_accounts import get_calendar_http
from app.services.capture import process_capture
from app.services.capture_parser import CaptureParser, get_capture_parser

router = APIRouter(prefix="/users/{user_id}", tags=["Capture"])


@router.post(
    "/captures",
    response_model=CaptureRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "A capture with this local_id was already processed."},
        409: {"description": "The time is taken or no free slot was found."},
        422: {"description": "The note could not be turned into an event."},
        503: {"description": "The language model is unavailable."},
    },
)
async def post_capture(
    user_id: uuid.UUID,
    capture_data: CaptureCreate,
    response: Response,
    session: AsyncSession = Depends(get_db),
    parser: CaptureParser = Depends(get_capture_parser),
    calendar_http: httpx.AsyncClient = Depends(get_calendar_http),
) -> CaptureRead:
    outcome = await process_capture(session, user_id, capture_data, parser, calendar_http)
    if not outcome.created:
        response.status_code = status.HTTP_200_OK

    capture = outcome.capture
    return CaptureRead(
        id=capture.id,
        status=capture.status,
        channel=capture.channel,
        transcription=capture.transcription,
        captured_at=capture.captured_at,
        processed_at=capture.processed_at,
        latency_ms=capture.latency_ms,
        event=EventRead.model_validate(outcome.event) if outcome.event else None,
        location_query=(capture.llm_result or {}).get("location_query"),
    )
