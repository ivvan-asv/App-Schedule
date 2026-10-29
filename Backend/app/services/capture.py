from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import time
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Capture, Event
from app.models.capture import CaptureStatus
from app.models.schedule import EventOrigin, EventPriority, EventStatus, EventType
from app.schemas.capture import CaptureCreate
from app.services.capture_parser import (
    CaptureNotUnderstood,
    CaptureParser,
    CaptureParserUnavailable,
    ResolvedCapture,
    resolve_capture,
)
from app.services.schedule import (
    ensure_no_overlap,
    find_available_slots,
    get_active_user,
    lock_active_user,
    user_timezone,
)

SLOT_STEP_MINUTES = 15
DEFAULT_SEARCH_HORIZON = timedelta(days=7)


@dataclass(frozen=True)
class CaptureOutcome:
    capture: Capture
    event: Event | None
    created: bool


async def _find_processed_capture(
    session: AsyncSession,
    user_id: uuid.UUID,
    local_id: uuid.UUID,
) -> CaptureOutcome | None:
    result = await session.execute(
        select(Capture, Event)
        .outerjoin(Event, Event.capture_id == Capture.id)
        .where(
            Capture.user_id == user_id,
            Capture.local_id == local_id,
            Capture.status == CaptureStatus.PROCESSED,
        )
        .limit(1)
    )
    row = result.first()
    if row is None:
        return None
    return CaptureOutcome(capture=row.Capture, event=row.Event, created=False)


def _round_up(moment: datetime, minutes: int) -> datetime:
    step = timedelta(minutes=minutes)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    remainder = (moment - epoch) % step
    return moment if remainder == timedelta(0) else moment + (step - remainder)


async def _choose_time(
    session: AsyncSession,
    user_id: uuid.UUID,
    resolved: ResolvedCapture,
    earliest: datetime,
    extra_busy: list[tuple[datetime, datetime]],
) -> tuple[datetime, datetime]:
    if resolved.start is not None:
        end = resolved.start + resolved.duration
        await ensure_no_overlap(session, user_id, resolved.start, end, extra_busy)
        return resolved.start, end

    range_start = _round_up(max(resolved.window_start or earliest, earliest), SLOT_STEP_MINUTES)
    range_end = resolved.window_end or range_start + DEFAULT_SEARCH_HORIZON
    if range_end <= range_start:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The requested time window has already passed",
        )

    slots = await find_available_slots(
        session,
        user_id,
        range_start,
        range_end,
        int(resolved.duration.total_seconds() // 60),
        SLOT_STEP_MINUTES,
        extra_busy,
    )
    if not slots:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No free slot is available in the requested time window",
        )
    return slots[0]


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


async def _record_failure(
    session: AsyncSession,
    capture: Capture,
    detail: str,
    started: float,
) -> None:
    await session.rollback()
    capture.status = CaptureStatus.ERROR
    capture.error_detail = detail
    capture.processed_at = datetime.now(UTC)
    capture.latency_ms = _elapsed_ms(started)
    session.add(capture)
    await session.commit()


async def process_capture(
    session: AsyncSession,
    user_id: uuid.UUID,
    capture_data: CaptureCreate,
    parser: CaptureParser,
) -> CaptureOutcome:
    """Turn a dictated note into a confirmed event in the user's agenda.

    The capture is stored in either case: as processed with its event, or as an
    error with the reason, which is then raised as an HTTP error.
    """
    started = time.perf_counter()
    user = await get_active_user(session, user_id)
    timezone = user_timezone(user)

    if capture_data.local_id is not None:
        existing = await _find_processed_capture(session, user_id, capture_data.local_id)
        if existing is not None:
            return existing

    capture = Capture(
        id=uuid.uuid4(),
        user_id=user_id,
        local_id=capture_data.local_id,
        channel=capture_data.channel,
        transcription=capture_data.text,
        stt_engine=capture_data.stt_engine,
        llm_model=parser.model_name,
        created_offline=capture_data.created_offline,
        captured_at=capture_data.captured_at,
        status=CaptureStatus.PROCESSING,
    )

    try:
        parsed = await parser.parse(
            capture_data.text,
            capture_data.captured_at.astimezone(timezone),
        )
        capture.llm_result = parsed.model_dump(mode="json")
        resolved = resolve_capture(parsed, timezone)

        await lock_active_user(session, user_id)
        if capture_data.local_id is not None:
            existing = await _find_processed_capture(session, user_id, capture_data.local_id)
            if existing is not None:
                return existing

        # Offline captures can arrive late; never schedule into the past.
        earliest = max(capture_data.captured_at, datetime.now(UTC))
        device_busy = [(busy.start, busy.end) for busy in capture_data.busy_intervals]
        start, end = await _choose_time(session, user_id, resolved, earliest, device_busy)
    except CaptureNotUnderstood as error:
        await _record_failure(session, capture, str(error), started)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except CaptureParserUnavailable as error:
        await _record_failure(session, capture, str(error), started)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except HTTPException as error:
        await _record_failure(session, capture, str(error.detail), started)
        raise

    event = Event(
        user_id=user_id,
        capture_id=capture.id,
        title=resolved.title,
        type=EventType(resolved.event_type),
        status=EventStatus.CONFIRMED,
        origin=EventOrigin.CAPTURE,
        priority=EventPriority(resolved.priority),
        start=start,
        end=end,
        flexible=resolved.start is None,
        window_start=resolved.window_start,
        window_end=resolved.window_end,
    )
    capture.status = CaptureStatus.PROCESSED
    capture.processed_at = datetime.now(UTC)
    capture.latency_ms = _elapsed_ms(started)
    session.add_all([capture, event])
    await session.commit()
    return CaptureOutcome(capture=capture, event=event, created=True)
