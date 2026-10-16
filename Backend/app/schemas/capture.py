from datetime import UTC, datetime
from typing import Annotated
import uuid

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.capture import CaptureChannel, CaptureStatus
from app.schemas.schedule import EventRead


class CaptureCreate(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    channel: CaptureChannel = CaptureChannel.TEXT
    local_id: uuid.UUID | None = Field(
        default=None,
        description="Client-generated id; resending it returns the original capture.",
    )
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the user dictated the note. Relative dates are read from here.",
    )
    created_offline: bool = False
    stt_engine: str | None = Field(default=None, max_length=40)

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value


class CaptureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: CaptureStatus
    channel: CaptureChannel
    transcription: str | None
    captured_at: datetime
    processed_at: datetime | None
    latency_ms: int | None
    event: EventRead | None
