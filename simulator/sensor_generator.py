"""Continuous multi-unit server room AC sensor simulator."""

from __future__ import annotations

import argparse
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import requests

from config import get_settings
from database.db import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class UnitSimulationState:
    unit_id: str
    step: int = 0
    degradation_level: float = 0.0
    fault_profile: str = "refrigerant_leak"
    drift_offset_temp: float = 0.0
    rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng(100))


class SensorSimulator:
    """Generates coherent time-stamped AC sensor readings across normal, warning, and critical states."""

    def __init__(self, seed: int = 2026) -> None:
        self.base_seed = seed
        self.unit_states: dict[str, UnitSimulationState] = {
            "AC-01": UnitSimulationState(
                unit_id="AC-01",
                fault_profile="refrigerant_leak",
                rng=np.random.default_rng(seed + 1),
            ),
            "AC-02": UnitSimulationState(
                unit_id="AC-02",
                fault_profile="fan_wear",
                rng=np.random.default_rng(seed + 2),
            ),
            "AC-03": UnitSimulationState(
                unit_id="AC-03",
                fault_profile="compressor_overload",
                rng=np.random.default_rng(seed + 3),
            ),
        }

    def get_unit_state(self, unit_id: str) -> UnitSimulationState:
        if unit_id not in self.unit_states:
            self.unit_states[unit_id] = UnitSimulationState(
                unit_id=unit_id,
                rng=np.random.default_rng(self.base_seed + len(self.unit_states) + 10),
            )
        return self.unit_states[unit_id]

    def generate_reading(
        self,
        unit_id: str,
        operating_mode: str = "normal",
        inject_missing: bool = True,
        inject_anomaly: bool = True,
    ) -> dict[str, Any]:
        """Generate one physically correlated reading for a unit given its operating mode."""
        state = self.get_unit_state(unit_id)
        state.step += 1
        rng = state.rng

        # Evolve degradation smoothly according to unit operating_mode
        if operating_mode == "critical":
            state.degradation_level = min(1.0, max(0.85, state.degradation_level + 0.08))
        elif operating_mode == "degrading":
            state.degradation_level = min(0.95, max(0.45, state.degradation_level + 0.05))
        else:
            # Normal mode recovers gradually or exhibits rare natural mild wear cycles
            if state.degradation_level > 0.0:
                state.degradation_level = max(0.0, state.degradation_level - 0.12)

        now = datetime.now(timezone.utc)
        hour = now.hour + now.minute / 60.0 + now.second / 3600.0
        diurnal = 0.5 + 0.5 * math.sin(2.0 * math.pi * (hour - 9.0) / 24.0)

        deg = state.degradation_level
        base_room_temp = 21.4 + 1.3 * diurnal + state.drift_offset_temp
        base_inlet_temp = base_room_temp + 2.1 + 0.3 * diurnal
        base_cooling_delta = 10.5
        base_humidity = 46.0 + 3.0 * math.cos(2.0 * math.pi * hour / 24.0)
        base_current = 12.8 + 1.8 * diurnal
        base_fan = 1590.0 + 95.0 * diurnal

        if deg > 0.0:
            if state.fault_profile == "refrigerant_leak":
                base_cooling_delta -= 6.5 * (deg ** 1.15)
                base_room_temp += 6.8 * (deg ** 1.2)
                base_inlet_temp += 7.2 * (deg ** 1.2)
                base_humidity += 15.0 * deg
                base_current += 3.0 * math.sin(math.pi * deg) - 1.2 * (deg ** 2)
                base_fan += 150.0 * deg
            elif state.fault_profile == "fan_wear":
                base_fan -= 720.0 * (deg ** 1.1)
                base_room_temp += 6.2 * (deg ** 1.25)
                base_inlet_temp += 6.6 * (deg ** 1.25)
                base_cooling_delta -= 4.3 * (deg ** 1.3)
                base_humidity += 12.0 * deg
                base_current += 2.8 * deg
            else:  # compressor_overload
                base_current += 8.2 * (deg ** 1.1)
                base_cooling_delta -= 5.2 * (deg ** 1.2)
                base_room_temp += 5.9 * (deg ** 1.25)
                base_inlet_temp += 6.4 * (deg ** 1.25)
                base_humidity += 13.0 * deg
                base_fan += 110.0 * deg

        room_temp: float | None = float(np.round(base_room_temp + rng.normal(0.0, 0.35), 2))
        ac_inlet_temp: float | None = float(np.round(base_inlet_temp + rng.normal(0.0, 0.40), 2))
        ac_outlet_temp: float | None = float(
            np.round(ac_inlet_temp - base_cooling_delta + rng.normal(0.0, 0.35), 2)
        )
        humidity: float | None = float(np.clip(np.round(base_humidity + rng.normal(0.0, 1.4), 2), 15.0, 95.0))
        compressor_current: float | None = float(
            np.clip(np.round(base_current + rng.normal(0.0, 0.45), 2), 0.5, 35.0)
        )
        fan_speed: float | None = float(
            np.clip(np.round(base_fan + rng.normal(0.0, 30.0), 1), 0.0, 2600.0)
        )

        # Occasional abnormal single-sensor spike (~1.5% chance)
        if inject_anomaly and operating_mode == "normal" and rng.random() < 0.015:
            room_temp = float(np.round(room_temp + float(rng.uniform(2.5, 4.0)), 2))

        # Occasional missing reading (~2.5% chance per tick on at most one sensor)
        if inject_missing and rng.random() < 0.025:
            sensor_choice = str(
                rng.choice(
                    [
                        "room_temp",
                        "ac_outlet_temp",
                        "ac_inlet_temp",
                        "humidity",
                        "compressor_current",
                        "fan_speed",
                    ]
                )
            )
            if sensor_choice == "room_temp":
                room_temp = None
            elif sensor_choice == "ac_outlet_temp":
                ac_outlet_temp = None
            elif sensor_choice == "ac_inlet_temp":
                ac_inlet_temp = None
            elif sensor_choice == "humidity":
                humidity = None
            elif sensor_choice == "compressor_current":
                compressor_current = None
            elif sensor_choice == "fan_speed":
                fan_speed = None

        return {
            "unit_id": unit_id,
            "recorded_at": now.isoformat(timespec="milliseconds"),
            "room_temp": room_temp,
            "ac_outlet_temp": ac_outlet_temp,
            "ac_inlet_temp": ac_inlet_temp,
            "humidity": humidity,
            "compressor_current": compressor_current,
            "fan_speed": fan_speed,
        }


def run_api_simulator_loop(api_base_url: str | None = None) -> None:
    """Continuously poll backend settings and push generated readings via FastAPI."""
    settings = get_settings()
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    simulator = SensorSimulator()

    logger.info("Starting continuous sensor simulator targeting %s", base_url)
    while True:
        interval = settings.simulator_interval_seconds
        enabled = True
        units: list[dict[str, Any]] = []

        try:
            status_resp = requests.get(f"{base_url}/api/v1/system/status", timeout=5)
            if status_resp.ok:
                sys_data = status_resp.json()
                sys_settings = sys_data.get("settings", {})
                enabled = str(sys_settings.get("simulator_enabled", "true")).lower() == "true"
                interval = max(1, int(float(sys_settings.get("simulator_interval_seconds", interval))))

            units_resp = requests.get(f"{base_url}/api/v1/units", timeout=5)
            if units_resp.ok:
                units = units_resp.json()
        except Exception as exc:
            logger.warning("Simulator unable to reach backend (%s); retrying in %ss", exc, interval)
            time.sleep(interval)
            continue

        if enabled and units:
            for unit in units:
                reading = simulator.generate_reading(
                    unit_id=unit["unit_id"],
                    operating_mode=unit.get("operating_mode", "normal"),
                )
                try:
                    resp = requests.post(f"{base_url}/api/v1/sensors/ingest", json=reading, timeout=5)
                    if not resp.ok:
                        logger.warning("Ingest failed for %s: %s", unit["unit_id"], resp.text)
                except Exception as exc:
                    logger.warning("Failed posting reading for %s: %s", unit["unit_id"], exc)

        time.sleep(interval)


def run_direct_db_tick(db: DatabaseManager, simulator: SensorSimulator) -> list[dict[str, Any]]:
    """Utility for generating one tick across all DB units without HTTP."""
    units = db.list_ac_units()
    generated: list[dict[str, Any]] = []
    for unit in units:
        reading = simulator.generate_reading(
            unit_id=unit["unit_id"],
            operating_mode=unit.get("operating_mode", "normal"),
        )
        generated.append(reading)
    return generated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Run Server Room AC sensor simulator.")
    parser.add_argument("--api-url", type=str, default=None, help="FastAPI base URL.")
    args = parser.parse_args()
    run_api_simulator_loop(api_base_url=args.api_url)
