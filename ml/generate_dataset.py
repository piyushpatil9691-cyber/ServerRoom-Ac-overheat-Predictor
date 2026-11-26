"""Synthetic historical dataset generator for Server Room AC predictive maintenance.

Generates multi-unit time-series sensor data with physically coherent cooling dynamics,
gradual degradation trajectories (refrigerant loss, fan bearing wear, compressor strain),
transient workload spikes (to avoid trivial separation), missing readings, and a
24-hour lookahead binary failure target (`failure_within_24h`).

Limitations:
- Simulated thermal and electrical curves approximate real CRAC units and cannot capture
  site-specific ductwork geometry, rare hardware faults, or seasonal ambient HVAC shifts
  absent in the simulation model.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import get_settings
from ml.features import SENSOR_FEATURES

TARGET_COLUMN = "failure_within_24h"


def generate_historical_dataset(
    output_path: str | Path | None = None,
    days: int = 90,
    interval_minutes: int = 15,
    units: tuple[str, ...] = ("AC-01", "AC-02", "AC-03"),
    seed: int = 42,
) -> pd.DataFrame:
    """Generate and persist a labeled historical sensor dataset without target leakage."""
    rng = np.random.default_rng(seed)
    steps_per_day = int((24 * 60) / interval_minutes)
    total_steps = days * steps_per_day
    lookahead_steps = int((24 * 60) / interval_minutes)  # 24-hour window

    start_ts = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    records: list[dict[str, object]] = []

    fault_types = ("refrigerant_leak", "fan_wear", "compressor_overload")

    for unit_idx, unit_id in enumerate(units):
        # Slight unit-specific calibration offsets
        unit_temp_offset = rng.normal(0.0, 0.35)
        unit_curr_offset = rng.normal(0.0, 0.4)

        # Schedule realistic failure events separated across the timeline
        failure_events: list[tuple[int, int, str]] = []
        cursor = int(rng.integers(steps_per_day * 3, steps_per_day * 8))
        while cursor < total_steps - steps_per_day * 2:
            # Degradation starts 18 to 44 hours before failure
            degrad_duration = int(rng.integers(int(18 * 60 / interval_minutes), int(44 * 60 / interval_minutes)))
            start_deg = max(0, cursor - degrad_duration)
            fault = fault_types[(len(failure_events) + unit_idx) % len(fault_types)]
            failure_events.append((start_deg, cursor, fault))
            # Maintenance resets unit after failure, next incident 7-15 days later
            cursor += int(rng.integers(steps_per_day * 7, steps_per_day * 15))

        # Transient non-failing heat spikes (realistic false-alarm stressors)
        transient_spikes: list[tuple[int, int]] = []
        for _ in range(max(4, days // 12)):
            s = int(rng.integers(0, total_steps - 16))
            transient_spikes.append((s, s + int(rng.integers(4, 14))))

        # Build step-by-step trajectory
        for step in range(total_steps):
            ts = start_ts + timedelta(minutes=step * interval_minutes)
            hour_of_day = ts.hour + ts.minute / 60.0
            # Diurnal server rack workload cycle
            diurnal = 0.5 + 0.5 * np.sin(2 * np.pi * (hour_of_day - 9.0) / 24.0)

            # Check if inside a degradation trajectory leading to failure
            deg_progress = 0.0
            active_fault = None
            for start_deg, fail_step, fault in failure_events:
                if start_deg <= step <= fail_step:
                    deg_progress = (step - start_deg) / max(1, (fail_step - start_deg))
                    active_fault = fault
                    break

            # Check if inside a transient workload spike (does NOT cause failure)
            spike_boost = 0.0
            for sp_start, sp_end in transient_spikes:
                if sp_start <= step <= sp_end:
                    spike_boost = 1.0
                    break

            # Base physical states
            base_room_temp = 21.2 + unit_temp_offset + 1.4 * diurnal + 1.9 * spike_boost
            base_inlet_temp = base_room_temp + 2.1 + 0.4 * diurnal + 0.6 * spike_boost
            base_cooling_delta = 10.6 - 0.5 * spike_boost
            base_humidity = 46.5 + 3.5 * np.cos(2 * np.pi * hour_of_day / 24.0) + 2.0 * spike_boost
            base_current = 12.6 + unit_curr_offset + 2.0 * diurnal + 2.4 * spike_boost
            base_fan = 1580.0 + 110.0 * diurnal + 80.0 * spike_boost

            # Apply gradual fault physics
            if active_fault == "refrigerant_leak":
                # Cooling delta collapses; room and inlet heat up; compressor works harder then drops
                base_cooling_delta -= 6.2 * (deg_progress ** 1.25)
                base_room_temp += 6.4 * (deg_progress ** 1.3)
                base_inlet_temp += 6.8 * (deg_progress ** 1.3)
                base_humidity += 15.0 * (deg_progress ** 1.1)
                base_current += 3.2 * np.sin(np.pi * deg_progress) - 1.5 * (deg_progress ** 2)
                base_fan += 140.0 * deg_progress
            elif active_fault == "fan_wear":
                # Fan slows down; airflow drops; room & inlet warm up; outlet gets slightly colder then warms
                base_fan -= 680.0 * (deg_progress ** 1.15)
                base_room_temp += 5.8 * (deg_progress ** 1.35)
                base_inlet_temp += 6.2 * (deg_progress ** 1.35)
                base_cooling_delta -= 4.1 * (deg_progress ** 1.5)
                base_humidity += 11.0 * deg_progress
                base_current += 2.6 * deg_progress
            elif active_fault == "compressor_overload":
                # Compressor current climbs steeply; cooling efficiency drops
                base_current += 7.8 * (deg_progress ** 1.15)
                base_cooling_delta -= 5.0 * (deg_progress ** 1.3)
                base_room_temp += 5.5 * (deg_progress ** 1.35)
                base_inlet_temp += 6.0 * (deg_progress ** 1.35)
                base_humidity += 12.0 * deg_progress
                base_fan += 110.0 * deg_progress

            # Add realistic sensor measurement noise
            room_temp = float(np.round(base_room_temp + rng.normal(0.0, 0.45), 2))
            ac_inlet_temp = float(np.round(base_inlet_temp + rng.normal(0.0, 0.50), 2))
            ac_outlet_temp = float(np.round(ac_inlet_temp - base_cooling_delta + rng.normal(0.0, 0.45), 2))
            humidity = float(np.clip(np.round(base_humidity + rng.normal(0.0, 1.8), 2), 15.0, 95.0))
            compressor_current = float(np.clip(np.round(base_current + rng.normal(0.0, 0.55), 2), 0.5, 35.0))
            fan_speed = float(np.clip(np.round(base_fan + rng.normal(0.0, 35.0), 1), 200.0, 2600.0))

            # Ground truth label: failure occurs in future 24h window (step, step + lookahead_steps]
            failure_within_24h = 0
            for _, fail_step, _ in failure_events:
                if step < fail_step <= step + lookahead_steps or step == fail_step:
                    failure_within_24h = 1
                    break

            records.append(
                {
                    "timestamp": ts.isoformat(),
                    "unit_id": unit_id,
                    "room_temp": room_temp,
                    "ac_outlet_temp": ac_outlet_temp,
                    "ac_inlet_temp": ac_inlet_temp,
                    "humidity": humidity,
                    "compressor_current": compressor_current,
                    "fan_speed": fan_speed,
                    TARGET_COLUMN: failure_within_24h,
                }
            )

    df = pd.DataFrame.from_records(records)

    # Inject ~2.5% missing readings randomly across sensor columns to exercise imputation
    missing_mask_rng = np.random.default_rng(seed + 99)
    for col in SENSOR_FEATURES:
        mask = missing_mask_rng.random(len(df)) < 0.025
        df.loc[mask, col] = np.nan

    target_path = Path(output_path) if output_path else get_settings().resolved_path(
        get_settings().historical_dataset_path
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(target_path, index=False)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic historical AC sensor dataset.")
    parser.add_argument("--output", type=str, default=None, help="Output CSV path.")
    parser.add_argument("--days", type=int, default=90, help="Number of simulated days per unit.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    args = parser.parse_args()

    df = generate_historical_dataset(output_path=args.output, days=args.days, seed=args.seed)
    pos_rate = df[TARGET_COLUMN].mean() * 100.0
    print(f"Generated {len(df)} rows across {df['unit_id'].nunique()} units.")
    print(f"Positive class ({TARGET_COLUMN}=1) prevalence: {pos_rate:.2f}%")


if __name__ == "__main__":
    main()
