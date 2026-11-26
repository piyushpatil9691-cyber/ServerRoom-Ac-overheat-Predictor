"""Tests for FastAPI endpoints, operator authorization, and credential non-exposure."""

from __future__ import annotations

from unittest.mock import patch


def test_system_and_unit_endpoints(api_client) -> None:
    client, _ = api_client
    r_health = client.get("/api/v1/system/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "healthy"
    assert r_health.json()["model_loaded"] is True

    r_status = client.get("/api/v1/system/status")
    assert r_status.status_code == 200
    assert r_status.json()["summary"]["total_units"] == 3

    r_units = client.get("/api/v1/units")
    assert r_units.status_code == 200
    assert len(r_units.json()) == 3

    r_perf = client.get("/api/v1/model/performance")
    assert r_perf.status_code == 200
    assert "metrics" in r_perf.json()


def test_email_config_security_and_operator_auth(api_client) -> None:
    client, env = api_client
    secret_pw = "my-gmail-app-password-16"

    # Unauthenticated mutation must fail with 403
    r_unauth = client.put(
        "/api/v1/email/config",
        json={
            "sender_email": "ops@gmail.com",
            "app_password": secret_pw,
            "recipient_email": "admin@example.com",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "use_starttls": True,
            "enabled": True,
        },
    )
    assert r_unauth.status_code == 403

    # Authorized mutation succeeds and NEVER returns the password
    headers = {"X-Operator-Key": env["operator_key"]}
    r_save = client.put(
        "/api/v1/email/config",
        headers=headers,
        json={
            "sender_email": "ops@gmail.com",
            "app_password": secret_pw,
            "recipient_email": "admin@example.com",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "use_starttls": True,
            "enabled": True,
        },
    )
    assert r_save.status_code == 200
    body_text = r_save.text
    assert secret_pw not in body_text
    assert "encrypted_app_password" not in body_text
    assert r_save.json()["has_app_password"] is True

    r_get = client.get("/api/v1/email/config")
    assert r_get.status_code == 200
    assert secret_pw not in r_get.text
    assert "encrypted_app_password" not in r_get.text

    with patch("alerts.email_service._send_smtp_message") as mock_smtp:
        r_test = client.post("/api/v1/email/test", headers=headers)
        assert r_test.status_code == 200
        assert r_test.json()["success"] is True
        assert mock_smtp.call_count == 1
        assert secret_pw not in r_test.text

    # Disabling email notifications works
    r_toggle = client.patch("/api/v1/email/toggle", headers=headers, json={"enabled": False})
    assert r_toggle.status_code == 200
    assert r_toggle.json()["enabled"] is False

    # Oversized password validation error must never echo submitted secret
    oversized_secret = "x" * 200
    r_val_err = client.put(
        "/api/v1/email/config",
        headers=headers,
        json={
            "sender_email": "ops@gmail.com",
            "app_password": oversized_secret,
            "recipient_email": "admin@example.com",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "use_starttls": True,
            "enabled": True,
        },
    )
    assert r_val_err.status_code == 422
    assert oversized_secret not in r_val_err.text
