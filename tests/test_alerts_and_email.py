"""Tests for alert engine, deduplication, cooldown, Fernet encryption, and Gmail SMTP."""

from __future__ import annotations

import logging
import smtplib
from unittest.mock import patch

from alerts.alert_service import AlertEngine
from alerts.email_service import EmailService
from security.credential_encryption import decrypt_secret, encrypt_secret, mask_secret


def test_fernet_encryption_roundtrip(isolated_env) -> None:
    secret = "abcd efgh ijkl mnop"
    token = encrypt_secret(secret)
    assert secret not in token
    assert decrypt_secret(token) == secret
    assert "abcd" not in mask_secret(token)


def test_alert_deduplication_cooldown_and_resolution(isolated_env) -> None:
    db = isolated_env["db"]
    email_svc = EmailService(db)
    engine = AlertEngine(db, email_svc)

    # Configure SMTP with dummy credentials & enabled=True
    db.save_email_settings(
        sender_email="sender@gmail.com",
        recipient_email="ops@example.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        use_starttls=True,
        enabled=True,
        encrypted_app_password=encrypt_secret("test-app-password"),
    )

    high_pred = {
        "failure_probability": 0.85,
        "predicted_class": 1,
        "risk_level": "High",
        "contributing_factors": [{"label": "Room Temperature", "value": 28.5, "unit": "°C"}],
    }
    reading = {
        "recorded_at": "2026-11-26T06:00:00+00:00",
        "room_temp": 28.5,
        "ac_outlet_temp": 21.0,
        "ac_inlet_temp": 30.0,
        "humidity": 65.0,
        "compressor_current": 20.1,
        "fan_speed": 950.0,
    }
    pred_id_1 = db.insert_prediction(
        {
            "unit_id": "AC-01",
            "failure_probability": 0.85,
            "predicted_class": 1,
            "risk_level": "High",
            "contributing_factors": [],
            "model_version": "rf-v1",
        }
    )

    with patch("alerts.email_service._send_smtp_message") as mock_smtp:
        a1 = engine.evaluate_prediction("AC-01", pred_id_1, high_pred, reading)
        assert a1 is not None
        assert a1["status"] == "active"
        assert a1["email_delivery_status"] == "sent"
        assert mock_smtp.call_count == 1

        # Second high prediction for same ongoing incident -> deduplicated, no duplicate alert, no repeat email
        pred_id_2 = db.insert_prediction(
            {
                "unit_id": "AC-01",
                "failure_probability": 0.92,
                "predicted_class": 1,
                "risk_level": "Critical",
                "contributing_factors": [],
                "model_version": "rf-v1",
            }
        )
        high_pred_2 = dict(high_pred, failure_probability=0.92, risk_level="Critical")
        a2 = engine.evaluate_prediction("AC-01", pred_id_2, high_pred_2, reading)
        assert a2 is not None
        assert a2["id"] == a1["id"]
        assert len(db.list_alerts(unit_id="AC-01")) == 1
        assert mock_smtp.call_count == 1

        # Acknowledge and resolve first incident
        db.transition_alert_status(a1["id"], "acknowledged", actor="op", notes="Investigating")
        db.transition_alert_status(a1["id"], "resolved", actor="op", notes="Cleaned condenser")

        # New incident right after resolution -> new alert created, email skipped due to 15-min cooldown
        a3 = engine.evaluate_prediction("AC-01", pred_id_2, high_pred_2, reading)
        assert a3 is not None
        assert a3["id"] != a1["id"]
        assert a3["email_delivery_status"] == "cooldown_skipped"
        assert len(db.list_alerts(unit_id="AC-01")) == 2
        assert mock_smtp.call_count == 1


def test_smtp_failure_preserves_dashboard_alert_and_never_logs_secret(isolated_env, caplog) -> None:
    db = isolated_env["db"]
    email_svc = EmailService(db)
    engine = AlertEngine(db, email_svc)

    secret_pw = "super-secret-gmail-app-pw"
    db.save_email_settings(
        sender_email="sender@gmail.com",
        recipient_email="ops@example.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        use_starttls=True,
        enabled=True,
        encrypted_app_password=encrypt_secret(secret_pw),
    )

    pred_id = db.insert_prediction(
        {
            "unit_id": "AC-02",
            "failure_probability": 0.91,
            "predicted_class": 1,
            "risk_level": "Critical",
            "contributing_factors": [],
            "model_version": "rf-v1",
        }
    )

    with caplog.at_level(logging.DEBUG):
        with patch(
            "alerts.email_service._send_smtp_message",
            side_effect=smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted"),
        ):
            alert = engine.evaluate_prediction(
                "AC-02",
                pred_id,
                {"failure_probability": 0.91, "predicted_class": 1, "risk_level": "Critical", "contributing_factors": []},
                {"room_temp": 29.0},
            )
            ok_test, msg_test = email_svc.send_test_email()

    assert alert is not None
    assert alert["status"] == "active"
    assert alert["email_delivery_status"] == "failed"
    assert db.get_alert(alert["id"]) is not None
    assert ok_test is False
    assert "authentication failed" in msg_test.lower()
    assert secret_pw not in caplog.text
    assert secret_pw not in msg_test
    assert secret_pw not in (alert.get("email_error") or "")
