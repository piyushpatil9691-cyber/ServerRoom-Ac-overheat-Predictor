"""Gmail SMTP configuration, encrypted persistence, toggle, and test email endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from alerts.email_service import EmailService, validate_email_address
from backend.dependencies import get_db, get_email_service, require_operator_auth
from backend.schemas import EmailConfigIn, EmailToggleIn
from database.db import DatabaseManager
from security.credential_encryption import EncryptionError, encrypt_secret

router = APIRouter(prefix="/api/v1/email", tags=["Email Notifications"])


@router.get("/config")
def get_email_config(email_svc: EmailService = Depends(get_email_service)) -> dict[str, Any]:
    """Return safe email configuration status without ever returning stored credentials."""
    return email_svc.get_safe_config_status()


def _upsert_email_config(
    payload: EmailConfigIn,
    db: DatabaseManager,
    email_svc: EmailService,
) -> dict[str, Any]:
    try:
        sender = validate_email_address(payload.sender_email)
        recipient = validate_email_address(payload.recipient_email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    existing = db.get_email_settings_row()
    encrypted_pw: str | None = None
    raw_pw = payload.app_password.get_secret_value().strip() if payload.app_password else ""

    if raw_pw:
        try:
            encrypted_pw = encrypt_secret(raw_pw)
        except EncryptionError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    elif not existing.get("encrypted_app_password"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Gmail App Password is required for initial SMTP configuration.",
        )

    db.save_email_settings(
        sender_email=sender,
        recipient_email=recipient,
        smtp_host=payload.smtp_host.strip(),
        smtp_port=payload.smtp_port,
        use_starttls=payload.use_starttls,
        enabled=payload.enabled,
        encrypted_app_password=encrypted_pw,
    )
    return email_svc.get_safe_config_status()


@router.post("/config")
def save_email_config(
    payload: EmailConfigIn,
    db: DatabaseManager = Depends(get_db),
    email_svc: EmailService = Depends(get_email_service),
    _actor: str = Depends(require_operator_auth),
) -> dict[str, Any]:
    return _upsert_email_config(payload, db, email_svc)


@router.put("/config")
def update_email_config(
    payload: EmailConfigIn,
    db: DatabaseManager = Depends(get_db),
    email_svc: EmailService = Depends(get_email_service),
    _actor: str = Depends(require_operator_auth),
) -> dict[str, Any]:
    return _upsert_email_config(payload, db, email_svc)


@router.patch("/toggle")
def toggle_email_notifications(
    payload: EmailToggleIn,
    db: DatabaseManager = Depends(get_db),
    email_svc: EmailService = Depends(get_email_service),
    _actor: str = Depends(require_operator_auth),
) -> dict[str, Any]:
    db.set_email_enabled(payload.enabled)
    return email_svc.get_safe_config_status()


@router.post("/test")
def test_email_connection(
    email_svc: EmailService = Depends(get_email_service),
    _actor: str = Depends(require_operator_auth),
) -> dict[str, Any]:
    success, message = email_svc.send_test_email()
    return {
        "success": success,
        "message": message,
        "config": email_svc.get_safe_config_status(),
    }
