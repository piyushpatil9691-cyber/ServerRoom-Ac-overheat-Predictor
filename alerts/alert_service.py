"""Background alert evaluation, deduplication, persistence, and email dispatch."""

from __future__ import annotations

import logging
from typing import Any

from alerts.alert_rules import build_recommended_action, evaluate_alert_trigger, is_within_cooldown
from alerts.email_service import EmailService
from database.db import DatabaseManager, utc_now_iso

logger = logging.getLogger(__name__)


class AlertEngine:
    """Evaluates predictions against threshold, manages deduplicated incidents, and sends alerts."""

    def __init__(self, db: DatabaseManager, email_service: EmailService | None = None) -> None:
        self.db = db
        self.email_service = email_service or EmailService(db)

    def _get_thresholds(self) -> tuple[float, int]:
        settings = self.db.get_system_settings()
        threshold = float(settings.get("alert_threshold", "0.70"))
        cooldown = int(float(settings.get("alert_cooldown_minutes", "15")))
        return threshold, cooldown

    def evaluate_prediction(
        self,
        unit_id: str,
        prediction_id: int,
        prediction: dict[str, Any],
        reading: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Evaluate a prediction and create or update an alert incident if threshold is exceeded."""
        threshold, cooldown_minutes = self._get_thresholds()
        prob = float(prediction["failure_probability"])
        should_trigger, risk_level, severity = evaluate_alert_trigger(prob, threshold=threshold)

        open_alert = self.db.get_open_alert_for_unit(unit_id)

        if not should_trigger:
            # Update unit status to reflect current non-alert risk state unless an open alert exists
            if open_alert:
                unit_status = "critical" if open_alert["severity"] == "critical" else "warning"
            elif risk_level == "Medium":
                unit_status = "warning"
            else:
                unit_status = "operational"
            self.db.update_ac_unit_status(unit_id, status=unit_status)
            return None

        # Unit has crossed alert threshold -> update unit operational status
        self.db.update_ac_unit_status(
            unit_id,
            status="critical" if severity == "critical" else "warning",
        )

        reading_snapshot = {
            "recorded_at": reading.get("recorded_at"),
            "room_temp": reading.get("room_temp"),
            "ac_outlet_temp": reading.get("ac_outlet_temp"),
            "ac_inlet_temp": reading.get("ac_inlet_temp"),
            "humidity": reading.get("humidity"),
            "compressor_current": reading.get("compressor_current"),
            "fan_speed": reading.get("fan_speed"),
        }

        if open_alert is not None:
            # Deduplication: update latest probability & readings on existing active/acknowledged incident
            self.db.update_open_alert_snapshot(
                alert_id=open_alert["id"],
                failure_probability=prob,
                risk_level=risk_level,
                severity=severity,
                triggering_readings=reading_snapshot,
            )
            return self.db.get_alert(open_alert["id"])

        # Check recent closed alert cooldown to prevent rapid repeat email spam
        last_alert = self.db.get_last_alert_for_unit(unit_id)
        in_cooldown = bool(
            last_alert and is_within_cooldown(last_alert.get("last_notified_at"), cooldown_minutes)
        )

        recommended_action = build_recommended_action(
            reading_snapshot,
            prediction.get("contributing_factors", []),
        )
        prob_pct = round(prob * 100.0, 1)
        alert_payload = {
            "unit_id": unit_id,
            "prediction_id": prediction_id,
            "failure_probability": prob,
            "risk_level": risk_level,
            "severity": severity,
            "status": "active",
            "title": f"{unit_id} {risk_level} Overheat Risk ({prob_pct}%)",
            "description": (
                f"Predicted 24-hour failure probability reached {prob_pct}% "
                f"(threshold {round(threshold * 100.0, 1)}%)."
            ),
            "recommended_action": recommended_action,
            "triggering_readings": reading_snapshot,
            "created_at": utc_now_iso(),
            "email_delivery_status": "cooldown_skipped" if in_cooldown else "pending",
        }
        alert_id = self.db.insert_alert(alert_payload)
        created_alert = self.db.get_alert(alert_id)
        assert created_alert is not None

        if not in_cooldown:
            # SMTP failure never deletes or suppresses the persisted dashboard alert
            delivery_status, email_error = self.email_service.send_incident_alert_email(created_alert)
            notified_at = utc_now_iso() if delivery_status == "sent" else None
            self.db.update_alert_notification(
                alert_id=alert_id,
                email_delivery_status=delivery_status,
                email_error=email_error,
                last_notified_at=notified_at,
            )
            created_alert = self.db.get_alert(alert_id)

        return created_alert
