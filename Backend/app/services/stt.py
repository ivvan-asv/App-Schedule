from app.schemas.event import IntentParseResponse
from app.services.llm import parse_intent


async def transcribe_and_parse(transcript: str, timezone: str) -> IntentParseResponse:
    """STT on-device (Apple Speech) / Whisper llega como texto ya transcrito en Fase 1.

    El audio crudo no se persiste: solo se interpreta el transcript volátil.
    """
    parsed, source = await parse_intent(transcript, timezone)
    return IntentParseResponse(parsed=parsed, source=source)
