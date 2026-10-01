from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ParsedEventSchema(BaseModel):
    title: str = Field(..., description="Título o descripción resumida del evento")
    start_time: datetime = Field(..., description="Fecha y hora de inicio estimada (ISO 8601)")
    duration_minutes: int = Field(default=30, ge=5, description="Duración estimada en minutos")
    location: Optional[str] = Field(None, description="Lugar físico o enlace virtual del evento")
    priority: str = Field(default="medium", description="Nivel de prioridad: low, medium, high")
    notes: Optional[str] = Field(None, description="Notas adicionales extraídas del comando")
    attendees: list[str] = Field(default_factory=list)
    needs_travel: bool = False
    origin_location: Optional[str] = None


class IntentParseRequest(BaseModel):
    text: str = Field(..., min_length=3)
    timezone: str = "America/Argentina/Buenos_Aires"
    origin_location: Optional[str] = None


class IntentParseResponse(BaseModel):
    parsed: ParsedEventSchema
    source: str
    travel_before_minutes: int = 0


class EventCreateRequest(BaseModel):
    title: str
    start_time: datetime
    duration_minutes: int = Field(default=30, ge=5)
    location: Optional[str] = None
    priority: str = "medium"
    notes: Optional[str] = None
    attendees: list[str] = Field(default_factory=list)
    source_text: Optional[str] = None
    travel_before_minutes: int = 0
    travel_after_minutes: int = 0
    commit_to_calendar: bool = True


class EventRead(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    start_time: datetime
    end_time: datetime
    location: Optional[str]
    priority: str
    notes: Optional[str]
    attendees: list[str]
    travel_before_minutes: int
    travel_after_minutes: int
    status: str
    calendar_provider: str
    external_id: Optional[str]
    source_text: Optional[str]

    model_config = {"from_attributes": True}


class OptimizeRequest(BaseModel):
    duration_minutes: int = Field(default=30, ge=5)
    window_start: datetime
    window_end: datetime
    location: Optional[str] = None
    origin_location: Optional[str] = None


class OptimizeResponse(BaseModel):
    suggested_start: datetime
    duration_minutes: int
    travel_before_minutes: int
    solver: str


class NegotiationCreateRequest(BaseModel):
    event_id: Optional[UUID] = None
    title: str
    duration_minutes: int = 30
    recipient: str
    channel: str = Field(default="email", pattern="^(whatsapp|sms|email)$")
    proposed_starts: list[datetime]


class NegotiationRead(BaseModel):
    id: UUID
    public_token: str
    title: str
    recipient: str
    channel: str
    proposed_starts: list[datetime]
    status: str
    confirm_url: str

    model_config = {"from_attributes": True}


class NegotiationConfirmRequest(BaseModel):
    token: str
    selected_start: datetime


class TranscribeRequest(BaseModel):
    transcript: Optional[str] = None
    timezone: str = "America/Argentina/Buenos_Aires"
