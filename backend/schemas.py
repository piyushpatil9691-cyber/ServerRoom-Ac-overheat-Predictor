"""Pydantic request and response schemas for the FastAPI backend."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr


class SensorReadingIn(BaseModel):
    unit_id: str = Field(..., min_length=1, max_length=32)
    recorded_at: str | None = None
    room_temp: float | None = None
    ac_outlet_temp: float | None = None
    ac_inlet_temp: float | None = None
    humidity: float | None = None
    compressor_current: float | None = None
    fan_speed: float | None = None


class UnitModeUpdate(BaseModel):
    operating_mode: Literal["normal", "degrading", "critical"]


class SystemSettingsUpdate(BaseModel):
    alert_threshold: float | None = Field(default=None, ge=0.05, le=0.99)
    alert_cooldown_minutes: int | None = Field(default=None, ge=1, le=1440)
    simulator_enabled: bool | None = None
    simulator_interval_seconds: int | None = Field(default=None, ge=1, le=300)
    dashboard_refresh_seconds: int | None = Field(default=None, ge=1, le=60)


class AlertActionIn(BaseModel):
    actor: str = Field(default="operator", min_length=1, max_length=64)
    notes: str = Field(default="", max_length=500)


class EmailConfigIn(BaseModel):
    sender_email: str = Field(..., min_length=3, max_length=254)
    app_password: SecretStr | None = Field(default=None, max_length=128)
    recipient_email: str = Field(..., min_length=3, max_length=254)
    smtp_host: str = Field(default="smtp.gmail.com", min_length=1, max_length=254)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    use_starttls: bool = Field(default=True)
    enabled: bool = Field(default=True)


class EmailToggleIn(BaseModel):
    enabled: bool


class EmailConfigSafeOut(BaseModel):
    sender_email: str
    recipient_email: str
    smtp_host: str
    smtp_port: int
    use_starttls: bool
    enabled: bool
    has_app_password: bool
    password_masked: str
    encryption_key_configured: bool
    is_configured: bool
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None
    updated_at: str | None = None
    extra: dict[str, Any] | None = None
