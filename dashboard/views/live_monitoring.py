"""Live Sensor Monitoring page displaying real-time metrics, quality, and drift warnings."""

from __future__ import annotations

import html
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
from dashboard.components.layout import (
    format_timestamp,
    render_html,
    render_kpi_strip,
    render_section_header,
    status_badge_html,
)


def _fmt(val: Any, unit: str, decimals: int = 1) -> str:
    if val is None:
        return "MISSING"
    return f"{float(val):.{decimals}f} {unit}"


def render(client: BackendClient, selected_unit: str, sys_status: dict[str, Any] | None) -> None:
    ok_units, units = client.list_units()
    if not ok_units or not units:
        st.error(f"Unable to load AC units: {units}")
        return

    unit_id = units[0]["unit_id"] if selected_unit == "All Units" else selected_unit
    ok_status, unit_status = client.get_unit_status(unit_id)
    ok_hist, history = client.get_sensor_history(unit_id=unit_id, limit=100)
    ok_qual, quality_summary = client.get_data_quality(unit_id=unit_id, limit=60)

    latest = (unit_status or {}).get("latest_reading") if ok_status else None
    drift = (unit_status or {}).get("drift") if ok_status else None
    unit_info = (unit_status or {}).get("unit") if ok_status else {}

    if not latest:
        st.info(f"No sensor readings recorded yet for {unit_id}. Ensure the simulator is running.")
        return

    render_section_header(f"Live Telemetry — {unit_id} ({unit_info.get('location', '')})")

    render_kpi_strip(
        [
            {
                "label": "Room Temperature",
                "value": _fmt(latest.get("room_temp"), "°C"),
                "sub": f"Timestamp: {format_timestamp(latest.get('recorded_at'))}",
                "tone": "crit" if (latest.get("room_temp") or 0) >= 28.5 else (
                    "warn" if (latest.get("room_temp") or 0) >= 26.0 else "ok"
                ),
            },
            {
                "label": "AC Inlet / Outlet",
                "value": f"{_fmt(latest.get('ac_inlet_temp'), '°C')} / {_fmt(latest.get('ac_outlet_temp'), '°C')}",
                "sub": (
                    f"Delta-T: {latest['ac_inlet_temp'] - latest['ac_outlet_temp']:.1f} °C"
                    if latest.get("ac_inlet_temp") is not None and latest.get("ac_outlet_temp") is not None
                    else "Delta-T: Unavailable (missing sensor)"
                ),
                "tone": "ok",
            },
            {
                "label": "Relative Humidity",
                "value": _fmt(latest.get("humidity"), "% RH"),
                "sub": "Acceptable band: 35% - 60% RH",
                "tone": "warn" if (latest.get("humidity") or 0) > 65.0 else "ok",
            },
            {
                "label": "Compressor / Fan",
                "value": f"{_fmt(latest.get('compressor_current'), 'A')} | {_fmt(latest.get('fan_speed'), 'RPM', 0)}",
                "sub": f"Quality status: {latest.get('quality_status', 'ok').upper()}",
                "tone": "warn" if latest.get("quality_status") != "ok" else "ok",
            },
        ]
    )

    q_col, d_col = st.columns(2, gap="medium")
    with q_col:
        render_section_header("Data Quality & Missing Sensor Check")
        q_stat = latest.get("quality_status", "ok")
        badge = status_badge_html(q_stat.upper(), "ok" if q_stat == "ok" else "warn")
        missing_count = (quality_summary or {}).get("missing_readings_count", 0) if ok_qual else 0
        out_range = (quality_summary or {}).get("out_of_range_count", 0) if ok_qual else 0
        render_html(
            f"""
            <div class="panel">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span>Latest Reading Status</span>{badge}
                </div>
                <div style="font-size:0.82rem; color:#8B949E; margin-top:8px;">
                    Recent window (60 samples): <strong>{missing_count}</strong> readings with missing sensors,
                    <strong>{out_range}</strong> out-of-range events. Genuine 0.0 values are preserved distinct from missing NULLs.
                </div>
                <div style="font-size:0.8rem; color:#C9D1D9; margin-top:6px;">
                    {html.escape(latest.get("quality_notes") or "All 6 sensors reporting within physical bounds.")}
                </div>
            </div>
            """
        )

    with d_col:
        render_section_header("Sensor Drift Monitor")
        d_stat = (drift or {}).get("status", "unavailable")
        drifting = (drift or {}).get("drifting_sensors", [])
        d_badge = status_badge_html(
            "DRIFT DETECTED" if d_stat == "drift_detected" else d_stat.upper(),
            "warn" if d_stat == "drift_detected" else "ok",
        )
        drift_desc = (
            f"Drifting sensors relative to healthy training baseline: {', '.join(drifting)}"
            if drifting
            else "Rolling sensor distribution aligns with healthy training baseline."
        )
        render_html(
            f"""
            <div class="panel">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span>Rolling Baseline Comparison (n={(drift or {}).get('sample_count', 0)})</span>{d_badge}
                </div>
                <div style="font-size:0.82rem; color:#C9D1D9; margin-top:8px;">
                    {html.escape(drift_desc)}
                </div>
                <div style="font-size:0.76rem; color:#8B949E; margin-top:6px;">
                    Note: Rolling baseline comparison cannot distinguish calibration drift from sustained heat load shifts.
                </div>
            </div>
            """
        )

    hist_list = history if ok_hist else []
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        st.plotly_chart(room_temperature_chart(hist_list, height=270), width="stretch", theme=None, config={"displayModeBar": False})
    with c2:
        st.plotly_chart(inlet_outlet_comparison_chart(hist_list, height=270), width="stretch", theme=None, config={"displayModeBar": False})

    c3, c4, c5 = st.columns(3, gap="medium")
    with c3:
        st.plotly_chart(humidity_chart(hist_list, height=250), width="stretch", theme=None, config={"displayModeBar": False})
    with c4:
        st.plotly_chart(compressor_current_chart(hist_list, height=250), width="stretch", theme=None, config={"displayModeBar": False})
    with c5:
        st.plotly_chart(fan_speed_chart(hist_list, height=250), width="stretch", theme=None, config={"displayModeBar": False})

    with st.expander("Recent Timestamped Sensor Log", expanded=False):
        if hist_list:
            df = pd.DataFrame(hist_list[:25])[
                [
                    "recorded_at",
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
            st.dataframe(df, width="stretch", hide_index=True)
