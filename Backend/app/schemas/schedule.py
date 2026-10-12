from datetime import datetime, time
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.schedule import AgendaRuleType, EventPriority, EventStatus, EventType


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
