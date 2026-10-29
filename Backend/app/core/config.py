import json

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Smart Scheduler AI"
    API_V1_PREFIX: str = Field(
        default="/api/v1",
        validation_alias=AliasChoices("API_V1_PREFIX", "API_V1_STR"),
    )
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgrespassword"
        "@localhost:5432/smart_scheduler_db"
    )
    REDIS_URL: str = "redis://localhost:6379/0"
    CORS_ORIGINS: str = ""
    ANTHROPIC_API_KEY: str | None = None
    CAPTURE_LLM_MODEL: str = "claude-haiku-5-5"

    # External calendars (RF07). See docs/calendar-credentials.md.
    # Public base URL of this API as the user's browser reaches it; the OAuth
    # redirect URI registered with each provider is
    # {OAUTH_REDIRECT_BASE_URL}{API_V1_PREFIX}/oauth/{google|microsoft}/callback.
    OAUTH_REDIRECT_BASE_URL: str = "http://localhost:8000"
    # Where the browser returns to the app when the connection finishes.
    APP_OAUTH_CALLBACK_URL: str = "smartscheduler://calendar-connected"
    # Base64 of 32 random bytes; encrypts stored OAuth tokens (AES-256-GCM).
    TOKEN_ENCRYPTION_KEY: str | None = None
    # The *_CALENDAR_* / *_GRAPH_* names from earlier .env files are accepted too.
    GOOGLE_CLIENT_ID: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_ID"),
    )
    GOOGLE_CLIENT_SECRET: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_CLIENT_SECRET", "GOOGLE_CALENDAR_CLIENT_SECRET"),
    )
    MICROSOFT_CLIENT_ID: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MICROSOFT_CLIENT_ID", "MICROSOFT_GRAPH_CLIENT_ID"),
    )
    MICROSOFT_CLIENT_SECRET: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MICROSOFT_CLIENT_SECRET", "MICROSOFT_GRAPH_CLIENT_SECRET"),
    )
    # "common" accepts work, school and personal accounts.
    MICROSOFT_TENANT: str = "common"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        if not self.CORS_ORIGINS:
            return []

        try:
            origins = json.loads(self.CORS_ORIGINS)
        except json.JSONDecodeError as error:
            if self.CORS_ORIGINS.lstrip().startswith(("[", "{")):
                raise ValueError(
                    "CORS_ORIGINS must be a valid JSON array or comma-separated list"
                ) from error
            return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

        if not isinstance(origins, list) or not all(
            isinstance(origin, str) for origin in origins
        ):
            raise ValueError("CORS_ORIGINS must be a JSON array or comma-separated list")
        return origins

settings = Settings()