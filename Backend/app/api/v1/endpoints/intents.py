from fastapi import APIRouter, HTTPException

from app.engine.travel import estimate_travel_minutes
from app.schemas.event import IntentParseRequest, IntentParseResponse, TranscribeRequest
from app.services.llm import parse_intent
from app.services.stt import transcribe_and_parse

router = APIRouter()


@router.post("/parse", response_model=IntentParseResponse)
async def parse_natural_language(payload: IntentParseRequest) -> IntentParseResponse:
    parsed, source = await parse_intent(payload.text, payload.timezone, payload.origin_location)
    travel = 0
    origin = payload.origin_location or parsed.origin_location
    if parsed.needs_travel:
        travel = await estimate_travel_minutes(origin, parsed.location)
    return IntentParseResponse(parsed=parsed, source=source, travel_before_minutes=travel)


@router.post("/transcribe", response_model=IntentParseResponse)
async def transcribe_intent(payload: TranscribeRequest) -> IntentParseResponse:
    if not payload.transcript:
        raise HTTPException(
            status_code=400,
            detail="En Fase 1 el cliente nativo envía el transcript (Apple Speech / Whisper). El audio no se persiste.",
        )
    return await transcribe_and_parse(payload.transcript, payload.timezone)
