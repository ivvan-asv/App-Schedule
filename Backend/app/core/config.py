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