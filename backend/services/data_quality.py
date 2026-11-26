"""Sensor data quality validation and statistical drift detection.

Limitations of the drift-detection approach:
- Compares recent rolling sensor means and empirical tail rates against the static
  healthy training baseline. Without external ground-truth calibration references,
  this method cannot strictly distinguish gradual sensor calibration drift from a
  sustained change in server room thermal load or active equipment degradation.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ml.features import SENSOR_FEATURES, SENSOR_METADATA

DRIFT_METHODOLOGY_LIMITATIONS = (
    "Drift detection compares rolling window statistics (last 20 readings per unit) against the "
    "healthy training baseline (mean, standard deviation, 5th-95th percentile). Because no secondary "
    "reference thermometer or calibration probe is present, sustained real workload heat shifts or "
    "early mechanical degradation can resemble sensor calibration drift until verified by maintenance."
)


def _is_missing_value(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    try:
        return math.isnan(float(val))
    except (TypeError, ValueError):
        return True


def evaluate_reading_quality(reading: dict[str, Any]) -> dict[str, Any]:
    """Validate an incoming reading, distinguishing missing values from genuine zero values."""
    missing_fields: list[str] = []
    out_of_range_fields: list[str] = []
    notes: list[str] = []

    sanitized: dict[str, Any] = dict(reading)

    for feat in SENSOR_FEATURES:
        raw_val = reading.get(feat)
        if _is_missing_value(raw_val):
            sanitized[feat] = None
            missing_fields.append(feat)
            continue

        num_val = float(raw_val)
        sanitized[feat] = num_val
        meta = SENSOR_METADATA[feat]
        # Genuine 0.0 is valid (e.g., stopped fan = 0 RPM) and NOT treated as missing
        if num_val < meta["physical_min"] or num_val > meta["physical_max"]:
            out_of_range_fields.append(feat)
            notes.append(
                f"{meta['label']} ({num_val} {meta['unit']}) outside physical bounds "
                f"[{meta['physical_min']}, {meta['physical_max']}]"
            )

    if missing_fields:
        labels = [SENSOR_METADATA[f]["label"] for f in missing_fields]
        notes.append(f"Missing sensor reading(s): {', '.join(labels)} (imputed at inference)")

    if out_of_range_fields:
        quality_status = "out_of_range"
    elif missing_fields:
        quality_status = "missing_values"
    else:
        quality_status = "ok"

    sanitized["is_missing_any"] = len(missing_fields) > 0
    sanitized["missing_fields"] = missing_fields
    sanitized["quality_status"] = quality_status
    sanitized["quality_notes"] = "; ".join(notes)
    return sanitized


def detect_sensor_drift(
    recent_readings: list[dict[str, Any]],
    baseline_stats: dict[str, dict[str, float]],
    z_threshold: float = 2.0,
    min_samples: int = 8,
) -> dict[str, Any]:
    """Evaluate per-sensor drift for a unit relative to the healthy training baseline."""
    if not baseline_stats:
        return {
            "status": "unavailable",
            "drifting_sensors": [],
            "sample_count": len(recent_readings),
            "sensors": {},
            "limitations": DRIFT_METHODOLOGY_LIMITATIONS,
        }

    sensors_report: dict[str, dict[str, Any]] = {}
    drifting_sensors: list[str] = []

    for feat in SENSOR_FEATURES:
        values = [
            float(r[feat])
            for r in recent_readings
            if r.get(feat) is not None and not _is_missing_value(r.get(feat))
        ]
        missing_count = sum(1 for r in recent_readings if _is_missing_value(r.get(feat)))
        stats = baseline_stats.get(feat, {})
        base_mean = stats.get("mean")
        base_std = stats.get("std", 1.0)
        p05 = stats.get("p05")
        p95 = stats.get("p95")
        meta = SENSOR_METADATA[feat]

        if len(values) < min_samples or base_mean is None:
            sensors_report[feat] = {
                "label": meta["label"],
                "unit": meta["unit"],
                "sample_count": len(values),
                "missing_count": missing_count,
                "current_mean": round(float(np.mean(values)), 2) if values else None,
                "baseline_mean": round(float(base_mean), 2) if base_mean is not None else None,
                "z_shift": None,
                "tail_exceedance_rate": None,
                "drift_detected": False,
                "severity": "insufficient_data",
            }
            continue

        arr = np.asarray(values, dtype=float)
        curr_mean = float(np.mean(arr))
        z_shift = (curr_mean - float(base_mean)) / max(float(base_std), 1e-4)

        tail_rate = 0.0
        if p05 is not None and p95 is not None:
            outside = np.sum((arr < float(p05)) | (arr > float(p95)))
            tail_rate = float(outside) / len(arr)

        drift_detected = abs(z_shift) >= z_threshold or tail_rate >= 0.45
        if abs(z_shift) >= 3.0 or tail_rate >= 0.70:
            severity = "severe"
        elif drift_detected:
            severity = "warning"
        else:
            severity = "normal"

        if drift_detected:
            drifting_sensors.append(feat)

        sensors_report[feat] = {
            "label": meta["label"],
            "unit": meta["unit"],
            "sample_count": len(values),
            "missing_count": missing_count,
            "current_mean": round(curr_mean, 2),
            "baseline_mean": round(float(base_mean), 2),
            "z_shift": round(float(z_shift), 2),
            "tail_exceedance_rate": round(float(tail_rate), 2),
            "drift_detected": drift_detected,
            "severity": severity,
        }

    overall_status = "drift_detected" if drifting_sensors else (
        "insufficient_data" if len(recent_readings) < min_samples else "nominal"
    )
    return {
        "status": overall_status,
        "drifting_sensors": drifting_sensors,
        "sample_count": len(recent_readings),
        "sensors": sensors_report,
        "limitations": DRIFT_METHODOLOGY_LIMITATIONS,
    }
