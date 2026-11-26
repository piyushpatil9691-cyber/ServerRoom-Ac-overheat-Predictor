"""Gmail SMTP notification service using STARTTLS and encrypted credentials."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from email_validator import EmailNotValidError, validate_email

from database.db import DatabaseManager, utc_now_iso
from security.credential_encryption import EncryptionError, decrypt_secret, is_encryption_configured

logger = logging.getLogger(__name__)


def validate_email_address(address: str) -> str:
    """Validate email syntax without performing external DNS lookups."""
    try:
        info = validate_email(address.strip(), check_deliverability=False)
        return info.normalized
    except EmailNotValidError as exc:
        raise ValueError(f"Invalid email address '{address}': {exc}") from exc


def _send_smtp_message(
    smtp_host: str,
    smtp_port: int,
    use_starttls: bool,
    sender_email: str,
    app_password: str,
    recipient_email: str,
    subject: str,
    body_text: str,
) -> None:
    msg = EmailMessage()
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.set_content(body_text)

    if use_starttls:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(sender_email, app_password)
            server.send_message(msg)
    else:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15, context=context) as server:
            server.ehlo()
            server.login(sender_email, app_password)
            server.send_message(msg)


class EmailService:
    """Handles safe SMTP configuration status, test emails, and alert email delivery."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def get_safe_config_status(self) -> dict[str, Any]:
        """Return SMTP settings without ever exposing encrypted or plaintext credentials."""
        row = self.db.get_email_settings_row()
        has_password = bool(row.get("encrypted_app_password"))
        enc_key_ok = is_encryption_configured()
        is_configured = bool(row.get("sender_email") and row.get("recipient_email") and has_password and enc_key_ok)
        return {
            "sender_email": row.get("sender_email", ""),
            "recipient_email": row.get("recipient_email", ""),
            "smtp_host": row.get("smtp_host", "smtp.gmail.com"),
            "smtp_port": int(row.get("smtp_port", 587)),
            "use_starttls": bool(row.get("use_starttls", True)),
            "enabled": bool(row.get("enabled", False)),
            "has_app_password": has_password,
            "password_masked": "•••••••••••• (Configured)" if has_password else "Not configured",
            "encryption_key_configured": enc_key_ok,
            "is_configured": is_configured,
            "last_test_status": row.get("last_test_status"),
            "last_test_message": row.get("last_test_message"),
            "last_test_at": row.get("last_test_at"),
            "updated_at": row.get("updated_at"),
        }

    def send_test_email(self) -> tuple[bool, str]:
        """Send a test email using persisted encrypted SMTP credentials."""
        row = self.db.get_email_settings_row()
        sender = (row.get("sender_email") or "").strip()
        recipient = (row.get("recipient_email") or "").strip()
        enc_pw = row.get("encrypted_app_password") or ""
        smtp_host = row.get("smtp_host") or "smtp.gmail.com"
        smtp_port = int(row.get("smtp_port") or 587)
        use_starttls = bool(row.get("use_starttls", True))

        if not sender or not recipient or not enc_pw:
            msg = "SMTP configuration is incomplete. Save sender email, Gmail App Password, and recipient email first."
            self.db.record_email_test_result("failed", msg)
            return False, msg

        try:
            app_password = decrypt_secret(enc_pw)
        except EncryptionError as exc:
            msg = f"Credential decryption failed: {exc}"
            self.db.record_email_test_result("failed", msg)
            return False, msg

        subject = "[Server Room AC Predictor] SMTP Test Connection Verified"
        body = (
            "This is a test notification from the Server Room AC Overheat Predictor.\n\n"
            f"Timestamp (UTC): {utc_now_iso()}\n"
            f"SMTP Host: {smtp_host}:{smtp_port} (STARTTLS={'Enabled' if use_starttls else 'SSL'})\n"
            f"Sender: {sender}\n"
            f"Recipient: {recipient}\n\n"
            "Your Gmail SMTP alert delivery configuration is active and verified."
        )

        try:
            _send_smtp_message(
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                use_starttls=use_starttls,
                sender_email=sender,
                app_password=app_password,
                recipient_email=recipient,
                subject=subject,
                body_text=body,
            )
            msg = f"Test email successfully sent to {recipient}."
            self.db.record_email_test_result("success", msg)
            logger.info("SMTP test email sent successfully to %s", recipient)
            return True, msg
        except smtplib.SMTPAuthenticationError:
            msg = (
                "SMTP authentication failed. Verify that 2-Step Verification is enabled on the Gmail account "
                "and that you entered a valid 16-character Google App Password (not your normal Gmail password)."
            )
            self.db.record_email_test_result("failed", msg)
            logger.warning("SMTP authentication failed during test email.")
            return False, msg
        except (smtplib.SMTPException, OSError) as exc:
            msg = f"SMTP connection error ({type(exc).__name__}): unable to deliver test email."
            self.db.record_email_test_result("failed", msg)
            logger.warning("SMTP error during test email: %s", type(exc).__name__)
            return False, msg

    def send_incident_alert_email(self, alert: dict[str, Any]) -> tuple[str, str | None]:
        """Deliver an incident alert email if enabled and configured.

        Returns (delivery_status, error_message_or_none).
        """
        row = self.db.get_email_settings_row()
        if not bool(row.get("enabled", False)):
            return "disabled", None

        sender = (row.get("sender_email") or "").strip()
        recipient = (row.get("recipient_email") or "").strip()
        enc_pw = row.get("encrypted_app_password") or ""
        smtp_host = row.get("smtp_host") or "smtp.gmail.com"
        smtp_port = int(row.get("smtp_port") or 587)
        use_starttls = bool(row.get("use_starttls", True))

        if not sender or not recipient or not enc_pw:
            return "not_configured", "Email notifications enabled, but SMTP settings are incomplete."

        try:
            app_password = decrypt_secret(enc_pw)
        except EncryptionError as exc:
            return "failed", f"Credential decryption error: {exc}"

        readings = alert.get("triggering_readings") or {}
        prob_pct = round(float(alert["failure_probability"]) * 100.0, 1)
        subject = (
            f"[{alert['risk_level'].upper()} ALERT] {alert['unit_id']} "
            f"AC Failure Probability {prob_pct}% (Next 24h)"
        )
        body = (
            "SERVER ROOM AC OVERHEAT PREDICTOR - PREDICTIVE MAINTENANCE ALERT\n"
            "==================================================================\n"
            f"Alert ID: {alert.get('id', 'N/A')}\n"
            f"AC Unit: {alert['unit_id']}\n"
            f"Risk Level: {alert['risk_level']} ({alert['severity'].upper()})\n"
            f"Predicted Failure Probability (24h): {prob_pct}%\n"
            f"Timestamp (UTC): {alert['created_at']}\n\n"
            "Triggering Sensor Readings:\n"
            f"  - Room Temperature:    {readings.get('room_temp', 'N/A')} °C\n"
            f"  - AC Inlet Temp:       {readings.get('ac_inlet_temp', 'N/A')} °C\n"
            f"  - AC Outlet Temp:      {readings.get('ac_outlet_temp', 'N/A')} °C\n"
            f"  - Humidity:            {readings.get('humidity', 'N/A')} % RH\n"
            f"  - Compressor Current:  {readings.get('compressor_current', 'N/A')} A\n"
            f"  - Fan Speed:           {readings.get('fan_speed', 'N/A')} RPM\n\n"
            "Recommended Inspection Action:\n"
            f"  {alert['recommended_action']}\n"
        )

        try:
            _send_smtp_message(
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                use_starttls=use_starttls,
                sender_email=sender,
                app_password=app_password,
                recipient_email=recipient,
                subject=subject,
                body_text=body,
            )
            logger.info("Incident alert email sent for alert_id=%s unit=%s", alert.get("id"), alert["unit_id"])
            return "sent", None
        except smtplib.SMTPAuthenticationError:
            err = "SMTP authentication failed. Check Gmail App Password configuration."
            logger.warning("SMTP auth failed for alert_id=%s", alert.get("id"))
            return "failed", err
        except (smtplib.SMTPException, OSError) as exc:
            err = f"SMTP delivery error ({type(exc).__name__})."
            logger.warning("SMTP delivery error for alert_id=%s: %s", alert.get("id"), type(exc).__name__)
            return "failed", err
