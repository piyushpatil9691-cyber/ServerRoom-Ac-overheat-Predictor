"""FastAPI shared application dependencies and operator authorization."""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, Request, status

from alerts.alert_service import AlertEngine
from alerts.email_service import EmailService
from backend.services.monitoring_service import MonitoringService
from backend.services.prediction_service import PredictionService
from config import get_settings
from database.db import DatabaseManager


def get_db(request: Request) -> DatabaseManager:
    return request.app.state.db


def get_prediction_service(request: Request) -> PredictionService:
    return request.app.state.prediction_service


def get_alert_engine(request: Request) -> AlertEngine:
    return request.app.state.alert_engine


def get_email_service(request: Request) -> EmailService:
    return request.app.state.email_service


def get_monitoring_service(request: Request) -> MonitoringService:
    return request.app.state.monitoring_service


def require_operator_auth(x_operator_key: str | None = Header(default=None)) -> str:
    """Verify operator access key for privileged configuration mutations."""
    expected = (os.environ.get("OPERATOR_ACCESS_KEY") or get_settings().operator_access_key or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator access control is not configured on the server (set OPERATOR_ACCESS_KEY).",
        )
    if not x_operator_key or not hmac.compare_digest(x_operator_key.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator authorization failed. Provide a valid X-Operator-Key header.",
        )
    return "operator"
