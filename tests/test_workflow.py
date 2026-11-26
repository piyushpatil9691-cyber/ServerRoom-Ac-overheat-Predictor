"""End-to-end workflow test covering ingestion, prediction, alerts, email, and restart persistence."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import create_app


def test_complete_predictive_maintenance_workflow(isolated_env) -> None:
    db_path = str(isolated_env["db_path"])
    model_path = str(isolated_env["model_path"])
    metrics_path = str(isolated_env["metrics_path"])
    headers = {"X-Operator-Key": isolated_env["operator_key"]}

    app1 = create_app(
        db_path=db_path,
        model_path=model_path,
        metrics_path=metrics_path,
        start_background_loop=False,
    )

    with TestClient(app1) as client:
        # 1. Configure Gmail SMTP via API
        r_email = client.put(
            "/api/v1/email/config",
            headers=headers,
            json={
                "sender_email": "facility.alerts@gmail.com",
                "app_password": "aaaa bbbb cccc dddd",
                "recipient_email": "engineer@example.com",
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "use_starttls": True,
                "enabled": True,
            },
        )
        assert r_email.status_code == 200

        # 2. Ingest nominal reading -> no alert
        r_norm = client.post(
            "/api/v1/sensors/ingest",
            json={
                "unit_id": "AC-01",
                "room_temp": 21.8,
                "ac_outlet_temp": 13.0,
                "ac_inlet_temp": 23.8,
                "humidity": 46.0,
                "compressor_current": 13.2,
                "fan_speed": 1610.0,
            },
        )
        assert r_norm.status_code == 201
        assert r_norm.json()["alert"] is None
        assert r_norm.json()["prediction"]["failure_probability"] < 0.70

        # 3. Trigger controlled high-risk incident -> alert created and email sent
        with patch("alerts.email_service._send_smtp_message") as mock_smtp:
            r_crit = client.post(
                "/api/v1/sensors/ingest",
                json={
                    "unit_id": "AC-01",
                    "room_temp": 30.2,
                    "ac_outlet_temp": 25.0,
                    "ac_inlet_temp": 31.8,
                    "humidity": 71.0,
                    "compressor_current": 22.0,
                    "fan_speed": 820.0,
                },
            )
            assert r_crit.status_code == 201
            data_crit = r_crit.json()
            assert data_crit["prediction"]["failure_probability"] >= 0.70
            assert data_crit["alert"] is not None
            assert data_crit["alert"]["email_delivery_status"] == "sent"
            assert mock_smtp.call_count == 1

        alert_id = data_crit["alert"]["id"]

        # 4. Acknowledge alert
        r_ack = client.post(f"/api/v1/alerts/{alert_id}/acknowledge", json={"actor": "admin", "notes": "Checking coil"})
        assert r_ack.status_code == 200
        assert r_ack.json()["status"] == "acknowledged"

    # 5. Simulate service restart with a fresh FastAPI instance pointing at same SQLite volume
    app2 = create_app(
        db_path=db_path,
        model_path=model_path,
        metrics_path=metrics_path,
        start_background_loop=False,
    )
    with TestClient(app2) as client2:
        r_cfg_after = client2.get("/api/v1/email/config")
        assert r_cfg_after.status_code == 200
        assert r_cfg_after.json()["is_configured"] is True
        assert r_cfg_after.json()["sender_email"] == "facility.alerts@gmail.com"
        assert "aaaa bbbb" not in r_cfg_after.text

        r_alerts_after = client2.get("/api/v1/alerts")
        assert r_alerts_after.status_code == 200
        assert len(r_alerts_after.json()) == 1
        assert r_alerts_after.json()[0]["status"] == "acknowledged"
