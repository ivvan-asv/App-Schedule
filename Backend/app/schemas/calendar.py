from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.calendar import CalendarAccountStatus, CalendarProvider


class CalendarProviderStatus(BaseModel):
    provider: CalendarProvider
    configured: bool
    missing_settings: list[str] = Field(description="Variables still empty in .env.")
    redirect_uri: str = Field(description="Register this exact URI with the provider.")


class CalendarAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: CalendarProvider
    external_email: str | None
    status: CalendarAccountStatus
    created_at: datetime


class AuthorizationStart(BaseModel):
    authorization_url: str
