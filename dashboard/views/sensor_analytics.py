"""Sensor Analytics page with date-range filtering, multi-sensor trends, and drift diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.api_client import BackendClient
from dashboard.components.charts import (
    compressor_current_chart,
    fan_speed_chart,
    humidity_chart,
    inlet_outlet_comparison_chart,
    room_temperature_chart,
)
from dashboard.components.layout import render_section_header


def render(client: BackendClient, selected_unit: str, sys_status: dict[str, Any] | None) -> None:
    render_section_header("Historical Query & Date-Range Filter")
    now_utc = datetime.now(timezone.utc)

    f1, f2, f3, f4 = st.columns([1.0, 1.0, 1.0, 0.8])
    with f1:
        start_date = st.date_input("Start Date (UTC)", value=(now_utc - timedelta(days=1)).date())
    with f2:
        end_date = st.date_input("End Date (UTC)", value=now_utc.date())
    with f3:
        sample_limit = st.selectbox("Max Readings", options=[100, 250, 500, 1000], index=1)
    with f4:
        drift_window = st.selectbox("Drift Window", options=[15, 20, 40, 60], index=1)

    start_iso = f"{start_date.isoformat()}T00:00:00+00:00"
    end_iso = f"{end_date.isoformat()}T23:59:59+00:00"
    unit_param = None if selected_unit == "All Units" else selected_unit

    ok_hist, history = client.get_sensor_history(
        unit_id=unit_param,
        start_time=start_iso,
        end_time=end_iso,
        limit=int(sample_limit),
    )

    hist_rows = history if ok_hist else []
    if not hist_rows:
        st.info("No historical sensor readings matched the selected date range and unit filter.")
        return

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        st.plotly_chart(room_temperature_chart(hist_rows, height=290), width="stretch", theme=None, config={"displayModeBar": False})
    with c2:
        inlet_rows = hist_rows if selected_unit != "All Units" else [
            r for r in hist_rows if r.get("unit_id") == hist_rows[0]["unit_id"]
        ]
        st.plotly_chart(inlet_outlet_comparison_chart(inlet_rows, height=290), width="stretch", theme=None, config={"displayModeBar": False})

    c3, c4, c5 = st.columns(3, gap="medium")
    with c3:
        st.plotly_chart(humidity_chart(hist_rows, height=270), width="stretch", theme=None, config={"displayModeBar": False})
    with c4:
        st.plotly_chart(compressor_current_chart(hist_rows, height=270), width="stretch", theme=None, config={"displayModeBar": False})
    with c5:
        st.plotly_chart(fan_speed_chart(hist_rows, height=270), width="stretch", theme=None, config={"displayModeBar": False})

    render_section_header("Sensor Drift Diagnostics vs. Healthy Baseline")
    drift_unit = hist_rows[0]["unit_id"] if selected_unit == "All Units" else selected_unit
    ok_drift, drift_report = client.get_sensor_drift(unit_id=drift_unit, window=int(drift_window))
    if ok_drift and drift_report:
        sensors_dict = drift_report.get("sensors", {})
        if sensors_dict:
            df_drift = pd.DataFrame.from_dict(sensors_dict, orient="index")
            df_drift = df_drift[
                [
                    "label",
                    "unit",
                    "sample_count",
                    "missing_count",
                    "current_mean",
                    "baseline_mean",
                    "z_shift",
                    "tail_exceedance_rate",
                    "severity",
                ]
            ]
            df_drift.columns = [
                "Sensor",
                "Unit",
                "Samples",
                "Missing",
                "Rolling Mean",
                "Baseline Mean",
                "Z-Shift",
                "Tail Exceedance",
                "Drift Status",
            ]
            st.dataframe(df_drift, width="stretch", hide_index=True)
        st.caption(f"Drift Limitations ({drift_unit}): {drift_report.get('limitations', '')}")

    render_section_header("Historical Sensor Readings Table")
    df_table = pd.DataFrame(hist_rows)[
        [
            "recorded_at",
            "unit_id",
            "room_temp",
            "ac_inlet_temp",
            "ac_outlet_temp",
            "humidity",
            "compressor_current",
            "fan_speed",
            "quality_status",
            "quality_notes",
        ]
    ]
    st.dataframe(df_table, width="stretch", hide_index=True, height=300)
