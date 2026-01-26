from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Peakon
    peakon_base_url: str = Field(default="https://pax8inc.peakon.com/api/v1", alias="PEAKON_BASE_URL")
    peakon_app_token: str | None = Field(default=None, alias="PEAKON_APP_TOKEN")
    peakon_company_id: int = Field(default=22182, alias="PEAKON_COMPANY_ID")
    peakon_engagement_group: str = Field(default="engagement", alias="PEAKON_ENGAGEMENT_GROUP")
    peakon_per_page: int = Field(default=10000, alias="PEAKON_PER_PAGE")
    http_timeout_seconds: int = Field(default=60, alias="HTTP_TIMEOUT_SECONDS")

    # Mongo
    mongo_uri: str = Field(default="mongodb://mongo:27017", alias="MONGO_URI")
    mongo_db: str = Field(default="peakon", alias="MONGO_DB")

    # Scheduler
    schedule_cron: str = Field(default="0 3 * * 1", alias="SCHEDULE_CRON")
    run_on_start: bool = Field(default=True, alias="RUN_ON_START")
    full_sync: bool = Field(default=False, alias="FULL_SYNC")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


def get_settings() -> Settings:
    return Settings()
