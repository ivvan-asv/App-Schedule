from datetime import datetime, time
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.schedule import (
    AgendaRuleType,
    EventPriority,
    EventStatus,
    EventType,
    TravelMode,
)

MAX_BUSY_INTERVALS = 500
MAX_TRAVEL_SECONDS = 12 * 60 * 60


class BusyInterval(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_range(self) -> "BusyInterval":
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("busy interval start and end must include a timezone")
        if self.end <= self.start:
            raise ValueError("busy interval end must be later than start")
        return self


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    type: Literal["tarea", "reunion"] = "tarea"
    priority: EventPriority = EventPriority.MEDIUM
    start: datetime
    end: datetime
    location_id: uuid.UUID | None = None
    flexible: bool = False

    @model_validator(mode="after")
    def validate_time_range(self) -> "EventCreate":
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("start and end must include a timezone")
        if self.end <= self.start:
            raise ValueError("end must be later than start")
        return self


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    type: EventType
    status: EventStatus
    priority: EventPriority
    start: datetime
    end: datetime
    location_id: uuid.UUID | None
    flexible: bool
    parent_id: uuid.UUID | None = None


class LocationCreate(BaseModel):
    alias: str | None = Field(default=None, max_length=80)
    address: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    place_id: str | None = Field(default=None, max_length=255)
    is_frequent: bool = False


class LocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alias: str | None
    address: str | None
    latitude: float
    longitude: float
    place_id: str | None
    is_frequent: bool


class TravelInput(BaseModel):
    """A travel time the app estimated with its map service (MapKit)."""

    origin_location_id: uuid.UUID | None = Field(
        default=None,
        description="Saved origin; null when the trip starts at the user's current position.",
    )
    duration_seconds: int = Field(ge=0, le=MAX_TRAVEL_SECONDS)
    distance_meters: int | None = Field(default=None, ge=0)
    mode: TravelMode = TravelMode.CAR
    provider: str = Field(default="mapkit", min_length=1, max_length=30)


class EventLocationUpdate(BaseModel):
    location_id: uuid.UUID | None = Field(default=None, description="A saved location.")
    location: LocationCreate | None = Field(
        default=None,
        description="A new place; reused when the user already saved the same one.",
    )
    travel: TravelInput | None = None
    busy_intervals: list[BusyInterval] = Field(
        default_factory=list,
        max_length=MAX_BUSY_INTERVALS,
        description="Device-calendar busy times, used if the event has to move.",
    )

    @model_validator(mode="after")
    def validate_destination(self) -> "EventLocationUpdate":
        if (self.location_id is None) == (self.location is None):
            raise ValueError("give exactly one of location_id or location")
        return self


class EventLocationRead(BaseModel):
    event: EventRead
    location: LocationRead
    travel: EventRead | None
    moved: bool = Field(description="A flexible event was moved so the trip fits.")
    travel_overlaps: bool = Field(
        description="The trip overlaps another commitment; the user may arrive late.",
    )


class AgendaRuleCreate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    weekdays: list[int] = Field(min_length=1, max_length=7)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def validate_rule(self) -> "AgendaRuleCreate":
        if self.start_time.tzinfo is not None or self.end_time.tzinfo is not None:
            raise ValueError("working-hours times must be local wall-clock times")
        if any(day < 1 or day > 7 for day in self.weekdays):
            raise ValueError("weekdays must use ISO values from 1 (Monday) to 7 (Sunday)")
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("weekdays must not contain duplicates")
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        return self


class WorkingHoursReplace(BaseModel):
    """The whole weekly schedule; it replaces every working-hours rule."""

    rules: list[AgendaRuleCreate] = Field(min_length=1, max_length=14)


class AgendaRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: AgendaRuleType
    name: str | None
    weekdays: list[int]
    start_time: time | None
    end_time: time | None
    active: bool


class AvailableSlot(BaseModel):
    start: datetime
    end: datetime
