"""Alert rules, risk mapping, inspection recommendations, and cooldown helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ml.features import SENSOR_METADATA, classify_risk_level


def severity_from_probability(probability: float) -> str:
    """Map failure probability to alert severity ('critical' or 'warning')."""
    if probability >= 0.90:
        return "critical"
    return "warning"


def build_recommended_action(readings: dict[str, Any], contributing_factors: list[dict[str, Any]]) -> str:
    """Generate a specific maintenance inspection recommendation from sensor anomalies."""
    actions: list[str] = []

    room_t = readings.get("room_temp")
    inlet_t = readings.get("ac_inlet_temp")
    outlet_t = readings.get("ac_outlet_temp")
    humidity = readings.get("humidity")
    current = readings.get("compressor_current")
    fan = readings.get("fan_speed")

    if inlet_t is not None and outlet_t is not None and (float(inlet_t) - float(outlet_t)) < 6.0:
        actions.append(
            "Low supply-return delta-T detected: inspect refrigerant charge, expansion valve, and evaporator/condenser coils."
        )
    if fan is not None and float(fan) < SENSOR_METADATA["fan_speed"]["warning_low"]:
        actions.append(
            "Reduced blower RPM detected: inspect fan motor bearings, belt tension, and air filter blockage."
        )
    if current is not None and float(current) > SENSOR_METADATA["compressor_current"]["warning_high"]:
        actions.append(
            "Elevated compressor draw detected: check compressor winding temperature, capacitor health, and head pressure."
        )
    if room_t is not None and float(room_t) > SENSOR_METADATA["room_temp"]["warning_high"]:
        actions.append(
            "Server room ambient temperature rising: verify hot/cold aisle containment and engage redundant CRAC unit."
        )
    if humidity is not None and float(humidity) > SENSOR_METADATA["humidity"]["warning_high"]:
        actions.append(
            "High relative humidity detected: check condensate drain line and dehumidification cycle."
        )

    if not actions and contributing_factors:
        top = contributing_factors[0]
        actions.append(
            f"Inspect {top.get('label', 'cooling subsystem')} (reading={top.get('value')} {top.get('unit', '')}) "
            "and verify unit cooling efficiency."
        )
    if not actions:
        actions.append("Perform immediate physical inspection of CRAC unit airflow, refrigerant, and electrical draw.")

    return " ".join(actions)


def is_within_cooldown(last_notified_at: str | None, cooldown_minutes: int, now: datetime | None = None) -> bool:
    """Return True if last notification timestamp is inside the configured cooldown window."""
    if not last_notified_at:
        return False
    current_time = now or datetime.now(timezone.utc)
    try:
        prev_time = datetime.fromisoformat(last_notified_at)
        if prev_time.tzinfo is None:
            prev_time = prev_time.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (current_time - prev_time) < timedelta(minutes=cooldown_minutes)


def evaluate_alert_trigger(probability: float, threshold: float = 0.70) -> tuple[bool, str, str]:
    """Return (should_trigger, risk_level, severity)."""
    risk_level = classify_risk_level(probability)
    severity = severity_from_probability(probability)
    return (probability >= threshold, risk_level, severity)
