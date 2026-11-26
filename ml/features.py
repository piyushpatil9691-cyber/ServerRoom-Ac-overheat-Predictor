"""Shared feature schema, physical bounds, and risk classification rules."""

from __future__ import annotations

from typing import Any

SENSOR_FEATURES: list[str] = [
    "room_temp",
    "ac_outlet_temp",
    "ac_inlet_temp",
    "humidity",
    "compressor_current",
    "fan_speed",
]

SENSOR_METADATA: dict[str, dict[str, Any]] = {
    "room_temp": {
        "label": "Room Temperature",
        "unit": "°C",
        "normal_min": 18.0,
        "normal_max": 25.0,
        "warning_high": 26.0,
        "critical_high": 28.5,
        "physical_min": -10.0,
        "physical_max": 70.0,
    },
    "ac_outlet_temp": {
        "label": "AC Outlet Temperature",
        "unit": "°C",
        "normal_min": 10.0,
        "normal_max": 16.5,
        "warning_high": 18.0,
        "critical_high": 21.0,
        "physical_min": -10.0,
        "physical_max": 60.0,
    },
    "ac_inlet_temp": {
        "label": "AC Inlet Temperature",
        "unit": "°C",
        "normal_min": 20.0,
        "normal_max": 28.0,
        "warning_high": 29.0,
        "critical_high": 32.0,
        "physical_min": -10.0,
        "physical_max": 70.0,
    },
    "humidity": {
        "label": "Humidity",
        "unit": "% RH",
        "normal_min": 35.0,
        "normal_max": 60.0,
        "warning_high": 65.0,
        "critical_high": 75.0,
        "physical_min": 0.0,
        "physical_max": 100.0,
    },
    "compressor_current": {
        "label": "Compressor Current",
        "unit": "A",
        "normal_min": 9.0,
        "normal_max": 17.0,
        "warning_high": 18.5,
        "critical_high": 21.0,
        "physical_min": 0.0,
        "physical_max": 60.0,
    },
    "fan_speed": {
        "label": "Fan Speed",
        "unit": "RPM",
        "normal_min": 1300.0,
        "normal_max": 1900.0,
        "warning_low": 1200.0,
        "critical_low": 1000.0,
        "physical_min": 0.0,
        "physical_max": 5000.0,
    },
}


def classify_risk_level(failure_probability: float) -> str:
    """Classify failure probability into Low, Medium, High, or Critical."""
    if failure_probability >= 0.90:
        return "Critical"
    if failure_probability >= 0.70:
        return "High"
    if failure_probability >= 0.40:
        return "Medium"
    return "Low"
