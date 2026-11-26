"""Tests for sensor simulation, quality validation, zero vs missing distinction, and drift detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.services.data_quality import detect_sensor_drift, evaluate_reading_quality
from ml.predict import ACFailurePredictor
from simulator.sensor_generator import SensorSimulator


def test_missing_vs_genuine_zero_distinction() -> None:
    reading = {
        "unit_id": "AC-01",
        "room_temp": 22.1,
        "ac_outlet_temp": 13.4,
        "ac_inlet_temp": 24.0,
        "humidity": None,
        "compressor_current": 12.8,
        "fan_speed": 0.0,  # Genuine 0 RPM (stopped fan), NOT missing!
    }
    q = evaluate_reading_quality(reading)
    assert q["is_missing_any"] is True
    assert q["missing_fields"] == ["humidity"]
    assert q["fan_speed"] == 0.0
    assert "fan_speed" not in q["missing_fields"]
    assert q["quality_status"] == "missing_values"


def test_out_of_range_detection() -> None:
    reading = {
        "unit_id": "AC-01",
        "room_temp": 120.0,
        "ac_outlet_temp": 13.0,
        "ac_inlet_temp": 24.0,
        "humidity": 48.0,
        "compressor_current": 13.0,
        "fan_speed": 1550.0,
    }
    q = evaluate_reading_quality(reading)
    assert q["quality_status"] == "out_of_range"
    assert "Room Temperature" in q["quality_notes"]


def test_simulator_and_drift_detection(trained_artifacts) -> None:
    sim = SensorSimulator(seed=7)
    r_norm = sim.generate_reading("AC-01", operating_mode="normal", inject_missing=False, inject_anomaly=False)
    for key in ("room_temp", "ac_outlet_temp", "ac_inlet_temp", "humidity", "compressor_current", "fan_speed"):
        assert r_norm[key] is not None

    predictor = ACFailurePredictor(
        model_path=trained_artifacts["model"],
        metrics_path=trained_artifacts["metrics"],
    )
    baseline = predictor.get_baseline_stats()

    # Drifted readings (room_temp shifted +6 C above baseline)
    drifted_rows = []
    for _ in range(15):
        drifted_rows.append(
            {
                "room_temp": 28.5,
                "ac_outlet_temp": 20.5,
                "ac_inlet_temp": 30.2,
                "humidity": 65.0,
                "compressor_current": 19.5,
                "fan_speed": 980.0,
            }
        )
    drift = detect_sensor_drift(drifted_rows, baseline, min_samples=8)
    assert drift["status"] == "drift_detected"
    assert "room_temp" in drift["drifting_sensors"]
    assert "limitations" in drift


def test_sqlite_persistence(isolated_env) -> None:
    db = isolated_env["db"]
    ts = datetime.now(timezone.utc).isoformat()
    rid = db.insert_sensor_reading(
        {
            "unit_id": "AC-01",
            "recorded_at": ts,
            "room_temp": 22.4,
            "ac_outlet_temp": 13.2,
            "ac_inlet_temp": 24.5,
            "humidity": 47.0,
            "compressor_current": 13.1,
            "fan_speed": 1600.0,
            "is_missing_any": False,
            "missing_fields": [],
            "quality_status": "ok",
            "quality_notes": "",
        }
    )
    assert rid > 0
    latest = db.get_latest_sensor_readings("AC-01")
    assert len(latest) == 1
    assert latest[0]["room_temp"] == 22.4
