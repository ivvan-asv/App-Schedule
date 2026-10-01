from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    PROJECT_NAME: str = "Smart Scheduler AI"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgrespassword@localhost:5432/smart_scheduler_db"
    REDIS_URL: str = "redis://localhost:6379/0"

    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GOOGLE_MAPS_API_KEY: str = ""
    META_WHATSAPP_TOKEN: str = ""
    GOOGLE_CALENDAR_CLIENT_ID: str = ""
    GOOGLE_CALENDAR_CLIENT_SECRET: str = ""
    MICROSOFT_GRAPH_CLIENT_ID: str = ""
    MICROSOFT_GRAPH_CLIENT_SECRET: str = ""

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8081"
    DEMO_USER_EMAIL: str = "demo@smartscheduler.local"
    DEMO_USER_TIMEZONE: str = "America/Argentina/Buenos_Aires"

    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]
        return origins or ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
