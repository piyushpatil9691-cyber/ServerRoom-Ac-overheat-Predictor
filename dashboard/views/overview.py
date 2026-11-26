"""Overview page implementing the purposeful 4-row industrial layout."""

from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.api_client import BackendClient
from dashboard.components.charts import (
    failure_probability_gauge,
    inlet_outlet_comparison_chart,
    prediction_probability_trend_chart,
    room_temperature_chart,
)
from dashboard.components.layout import (
    format_timestamp,
    render_html,
    render_kpi_strip,
    render_section_header,
    status_badge_html,
)


def render(client: BackendClient, selected_unit: str, sys_status: dict[str, Any] | None) -> None:
    ok_units, units = client.list_units()
    ok_latest_s, latest_sensors = client.get_latest_sensors()
    ok_latest_p, latest_preds = client.get_latest_predictions()
    unit_param = None if selected_unit == "All Units" else selected_unit
    ok_hist, sensor_history = client.get_sensor_history(unit_id=unit_param, limit=120)
    ok_pred_hist, pred_history = client.get_prediction_history(unit_id=unit_param, limit=120)
    ok_alerts, alerts = client.list_alerts(limit=12)

    if not ok_units:
        st.error(f"Unable to load AC unit telemetry from backend: {units}")
        return

    units_list = units or []
    latest_s_map = {r["unit_id"]: r for r in (latest_sensors or [])} if ok_latest_s else {}
    latest_p_map = {p["unit_id"]: p for p in (latest_preds or [])} if ok_latest_p else {}

    summary = (sys_status or {}).get("summary", {})
    settings = (sys_status or {}).get("settings", {})
    threshold = float(settings.get("alert_threshold", "0.70"))

    total_units = int(summary.get("total_units", len(units_list)))
    operational_units = int(summary.get("operational_units", 0))
    attention_units = int(summary.get("attention_units", 0))
    active_alerts = int(summary.get("active_alerts", 0))

    focus_unit = units_list[0]["unit_id"] if (selected_unit == "All Units" and units_list) else selected_unit
    focus_reading = latest_s_map.get(focus_unit, {})
    focus_pred = latest_p_map.get(focus_unit, {})

    highest_prob = max((p.get("failure_probability", 0.0) for p in latest_p_map.values()), default=0.0)
    room_temp_val = focus_reading.get("room_temp")
    humidity_val = focus_reading.get("humidity")
    overall_status = "ATTENTION REQUIRED" if attention_units > 0 or active_alerts > 0 else "OPERATIONAL"

    # Row 1: KPI summary strip
    render_kpi_strip(
        [
            {
                "label": "Monitored AC Units",
                "value": str(total_units),
                "sub": f"{operational_units} operational / {attention_units} requiring attention",
                "tone": "warn" if attention_units > 0 else "ok",
            },
            {
                "label": "Active Alerts",
                "value": str(active_alerts),
                "sub": f"System status: {overall_status}",
                "tone": "crit" if active_alerts > 0 else "ok",
            },
            {
                "label": f"Room Temp ({focus_unit})",
                "value": f"{room_temp_val:.1f} °C" if room_temp_val is not None else "--",
                "sub": f"Humidity: {humidity_val:.1f}% RH" if humidity_val is not None else "Humidity: --",
                "tone": "crit" if (room_temp_val is not None and room_temp_val >= 28.5) else (
                    "warn" if (room_temp_val is not None and room_temp_val >= 26.0) else "ok"
                ),
            },
            {
                "label": "Peak Failure Risk (24h)",
                "value": f"{highest_prob * 100:.1f}%",
                "sub": f"Alert threshold: {threshold * 100:.0f}%",
                "tone": "crit" if highest_prob >= 0.90 else ("warn" if highest_prob >= threshold else "ok"),
            },
        ]
    )

    # Row 2: Room temperature trend + AC cooling performance (Inlet vs Outlet)
    col_temp, col_cool = st.columns([1.15, 1.0], gap="medium")
    with col_temp:
        st.plotly_chart(
            room_temperature_chart(sensor_history if ok_hist else [], height=310),
            width="stretch",
            theme=None,
            config={"displayModeBar": False},
        )
    with col_cool:
        inlet_history = [
            r for r in (sensor_history if ok_hist else [])
            if r.get("unit_id") == focus_unit
        ]
        st.plotly_chart(
            inlet_outlet_comparison_chart(inlet_history, height=310),
            width="stretch",
            theme=None,
            config={"displayModeBar": False},
        )

    # Row 3: Failure probability gauge + Sensor status summary + Recent alert activity
    col_prob, col_status, col_alerts = st.columns([0.9, 1.05, 1.05], gap="medium")

    with col_prob:
        render_section_header("Failure Probability")
        prob_val = float(focus_pred.get("failure_probability", 0.0)) if focus_pred else 0.0
        st.plotly_chart(
            failure_probability_gauge(prob_val, threshold=threshold, unit_id=focus_unit),
            width="stretch",
            theme=None,
            config={"displayModeBar": False},
        )
        if focus_pred:
            risk_lvl = focus_pred.get("risk_level", "Low")
            pred_status = "Failure Predicted (<=24h)" if focus_pred.get("predicted_class") == 1 else "Normal Operation"
            render_html(
                f'<div>{status_badge_html(risk_lvl, risk_lvl)} &nbsp; <strong>{html.escape(pred_status)}</strong></div>'
            )

    with col_status:
        render_section_header("Unit & Sensor Status")
        for u in units_list:
            uid = u["unit_id"]
            r = latest_s_map.get(uid, {})
            p = latest_p_map.get(uid, {})
            u_prob = f"{p['failure_probability']*100:.1f}%" if p else "--"
            u_temp = f"{r['room_temp']:.1f}°C" if r.get("room_temp") is not None else "Missing"
            u_fan = f"{r['fan_speed']:.0f} RPM" if r.get("fan_speed") is not None else "Missing"
            q_status = r.get("quality_status", "ok")
            badge = status_badge_html(u["status"], u["status"])
            q_note = " | Quality: " + q_status if q_status != "ok" else ""
            render_html(
                f"""
                <div class="panel" style="padding:10px 12px; margin-bottom:8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <strong>{html.escape(uid)} — {html.escape(u['name'])}</strong>
                        {badge}
                    </div>
                    <div style="font-size:0.78rem; color:#8B949E; margin-top:4px;">
                        Room: {u_temp} | Fan: {u_fan} | Risk: {u_prob}{html.escape(q_note)}
                    </div>
                </div>
                """
            )

    with col_alerts:
        render_section_header("Recent Alert Activity")
        alert_items = alerts if ok_alerts and alerts else []
        if not alert_items:
            st.info("No alerts recorded yet. Monitoring continues in the background.")
        else:
            for al in alert_items[:4]:
                sev = al.get("severity", "warning")
                row_cls = "alert-row alert-row-crit" if sev == "critical" else "alert-row alert-row-warn"
                render_html(
                    f"""
                    <div class="{row_cls}" style="padding:9px 12px; margin-bottom:7px;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <strong style="font-size:0.84rem;">{html.escape(al['title'])}</strong>
                            {status_badge_html(al['status'], al['status'])}
                        </div>
                        <div style="font-size:0.74rem; color:#8B949E; margin-top:4px;">
                            {html.escape(format_timestamp(al['created_at']))} | Email: {html.escape(al.get('email_delivery_status', 'n/a'))}
                        </div>
                    </div>
                    """
                )

    # Row 4: Historical performance & Recent sensor readings
    col_hist_p, col_recent_s = st.columns([1.0, 1.15], gap="medium")
    with col_hist_p:
        render_section_header("Historical Failure Risk")
        st.plotly_chart(
            prediction_probability_trend_chart(pred_history if ok_pred_hist else [], threshold=threshold, height=270),
            width="stretch",
            theme=None,
            config={"displayModeBar": False},
        )
    with col_recent_s:
        render_section_header("Recent Sensor Readings")
        rows = (sensor_history if ok_hist else [])[:8]
        if rows:
            df_show = pd.DataFrame(rows)[
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
                ]
            ]
            df_show.columns = [
                "Timestamp",
                "Unit",
                "Room °C",
                "Inlet °C",
                "Outlet °C",
                "Humidity %",
                "Current A",
                "Fan RPM",
                "Quality",
            ]
            st.dataframe(df_show, width="stretch", hide_index=True, height=255)
        else:
            st.info("Waiting for sensor readings...")
