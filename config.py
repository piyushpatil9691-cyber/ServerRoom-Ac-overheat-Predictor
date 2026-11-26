"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    """Runtime settings for backend, ML, simulator, alerts, and dashboard."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_path: str = Field(default=str(PROJECT_ROOT / "data" / "ac_predictor.db"))
    model_path: str = Field(default=str(PROJECT_ROOT / "ml" / "models" / "ac_failure_model.joblib"))
    metrics_path: str = Field(default=str(PROJECT_ROOT / "ml" / "models" / "model_evaluation.json"))
    historical_dataset_path: str = Field(
        default=str(PROJECT_ROOT / "data" / "historical" / "server_room_ac_historical.csv")
    )

    credentials_encryption_key: str = Field(default="")
    operator_access_key: str = Field(default="")

    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000)
    api_base_url: str = Field(default="http://localhost:8000")

    simulator_interval_seconds: int = Field(default=3, ge=1, le=300)
    simulator_enabled: bool = Field(default=True)
    in_process_simulator: bool = Field(default=False)

    alert_threshold: float = Field(default=0.70, ge=0.05, le=0.99)
    alert_cooldown_minutes: int = Field(default=15, ge=1, le=1440)
    alert_poll_interval_seconds: int = Field(default=3, ge=1, le=60)

    dashboard_refresh_seconds: int = Field(default=3, ge=1, le=60)

    def resolved_path(self, raw_path: str) -> Path:
        p = Path(raw_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


def reload_settings() -> Settings:
    """Clear cache and reload settings from environment."""
    get_settings.cache_clear()
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    return get_settings()
