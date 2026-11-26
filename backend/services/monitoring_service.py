"""Monitoring pipeline service orchestrating ingestion, quality, prediction, and alerts."""

from __future__ import annotations

import logging
from typing import Any

from alerts.alert_service import AlertEngine
from backend.services.data_quality import detect_sensor_drift, evaluate_reading_quality
from backend.services.prediction_service import PredictionService
from database.db import DatabaseManager, utc_now_iso

logger = logging.getLogger(__name__)


class MonitoringService:
    """Processes incoming sensor readings through quality validation, ML prediction, and alerting."""

    def __init__(
        self,
        db: DatabaseManager,
        prediction_service: PredictionService,
        alert_engine: AlertEngine,
    ) -> None:
        self.db = db
        self.prediction_service = prediction_service
        self.alert_engine = alert_engine

    def process_reading(self, raw_reading: dict[str, Any]) -> dict[str, Any]:
        """Validate, store, predict, and evaluate alert rules for one sensor reading."""
        unit_id = raw_reading["unit_id"]
        if not raw_reading.get("recorded_at"):
            raw_reading["recorded_at"] = utc_now_iso()

        sanitized = evaluate_reading_quality(raw_reading)

        # Check drift on recent history (only upgrade 'ok' -> 'drift_warning' if drift is present)
        if self.prediction_service.predictor.is_loaded():
            recent = self.db.get_sensor_history(unit_id=unit_id, limit=20)
            baseline = self.prediction_service.predictor.get_baseline_stats()
            drift_report = detect_sensor_drift([sanitized, *recent], baseline)
            if drift_report.get("status") == "drift_detected" and sanitized["quality_status"] == "ok":
                sanitized["quality_status"] = "drift_warning"
                drifting = ", ".join(drift_report["drifting_sensors"])
                sanitized["quality_notes"] = (
                    f"{sanitized['quality_notes']}; " if sanitized["quality_notes"] else ""
                ) + f"Baseline drift detected in: {drifting}"

        reading_id = self.db.insert_sensor_reading(sanitized)
        sanitized["id"] = reading_id

        prediction = self.prediction_service.predict_and_store(sanitized, reading_id=reading_id)
        alert = self.alert_engine.evaluate_prediction(
            unit_id=unit_id,
            prediction_id=prediction["id"],
            prediction=prediction,
            reading=sanitized,
        )

        return {
            "reading": sanitized,
            "prediction": prediction,
            "alert": alert,
        }

    def get_unit_drift_report(self, unit_id: str, window_size: int = 20) -> dict[str, Any]:
        recent = self.db.get_sensor_history(unit_id=unit_id, limit=window_size)
        baseline = (
            self.prediction_service.predictor.get_baseline_stats()
            if self.prediction_service.predictor.is_loaded()
            else {}
        )
        report = detect_sensor_drift(recent, baseline)
        report["unit_id"] = unit_id
        return report
