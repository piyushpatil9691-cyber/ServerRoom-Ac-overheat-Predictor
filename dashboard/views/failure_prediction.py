"""Failure Prediction page showing ML probabilities, risk levels, factors, and history."""

from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.api_client import BackendClient
from dashboard.components.charts import failure_probability_gauge, prediction_probability_trend_chart
from dashboard.components.layout import format_timestamp, render_html, render_section_header, status_badge_html


def render(client: BackendClient, selected_unit: str, sys_status: dict[str, Any] | None) -> None:
    ok_units, units = client.list_units()
    if not ok_units or not units:
        st.error(f"Unable to load AC units: {units}")
        return

    unit_id = units[0]["unit_id"] if selected_unit == "All Units" else selected_unit
    settings = (sys_status or {}).get("settings", {})
    threshold = float(settings.get("alert_threshold", "0.70"))

    ok_latest_p, latest_preds = client.get_latest_predictions(unit_id=unit_id)
    ok_hist_p, pred_history = client.get_prediction_history(
        unit_id=None if selected_unit == "All Units" else unit_id,
        limit=150,
    )

    latest = latest_preds[0] if (ok_latest_p and latest_preds) else None
    if not latest:
        st.info(f"No failure predictions generated yet for {unit_id}.")
        return

    prob = float(latest["failure_probability"])
    risk_level = latest["risk_level"]
    pred_status = "Failure Predicted (<=24h)" if latest["predicted_class"] == 1 else "Normal Operation"

    col_gauge, col_details = st.columns([0.95, 1.45], gap="medium")
    with col_gauge:
        render_section_header(f"24-Hour Failure Forecast — {unit_id}")
        st.plotly_chart(
            failure_probability_gauge(prob, threshold=threshold, unit_id=unit_id),
            width="stretch",
            theme=None,
            config={"displayModeBar": False},
        )
        render_html(
            f"""
            <div class="panel">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span>Predicted Status</span>
                    {status_badge_html(risk_level + " RISK", risk_level)}
                </div>
                <div style="font-size:1.0rem; font-weight:600; margin-top:8px;">
                    {html.escape(pred_status)} ({prob * 100:.2f}%)
                </div>
                <div style="font-size:0.78rem; color:#8B949E; margin-top:6px;">
                    Evaluated: {html.escape(format_timestamp(latest.get('predicted_at')))} |
                    Model: {html.escape(latest.get('model_version', 'rf-ac-predictor-v1.0'))} |
                    Alert Threshold: {threshold * 100:.0f}%
                </div>
            </div>
            """
        )

    with col_details:
        render_section_header("Main Contributing Sensor Factors")
        factors = latest.get("contributing_factors", [])
        if factors:
            df_factors = pd.DataFrame(factors)[
                ["label", "value", "unit", "baseline_mean", "z_score", "direction", "model_importance"]
            ]
            df_factors.columns = [
                "Sensor Metric",
                "Current Value",
                "Unit",
                "Healthy Baseline",
                "Z-Score",
                "State",
                "Model Weight",
            ]
            df_factors["Model Weight"] = (df_factors["Model Weight"] * 100).round(2).astype(str) + "%"
            st.dataframe(df_factors, width="stretch", hide_index=True, height=270)

        render_html(
            """
            <div style="font-size:0.78rem; color:#8B949E; margin-top:6px;">
                Risk Classification Scale: Low (&lt;40%) | Medium (40% to &lt;70%) |
                High (70% to &lt;90%) | Critical (&ge;90%).
            </div>
            """
        )

    render_section_header("Prediction History & Timeline")
    hist_rows = pred_history if ok_hist_p else []
    st.plotly_chart(
        prediction_probability_trend_chart(hist_rows, threshold=threshold, height=290),
        width="stretch",
        theme=None,
        config={"displayModeBar": False},
    )

    if hist_rows:
        df_hist = pd.DataFrame(hist_rows[:50])[
            ["predicted_at", "unit_id", "failure_probability", "risk_level", "predicted_class", "model_version"]
        ]
        df_hist["failure_probability"] = (df_hist["failure_probability"] * 100).round(2).astype(str) + "%"
        df_hist["predicted_class"] = df_hist["predicted_class"].map({0: "Normal (0)", 1: "Failure <=24h (1)"})
        df_hist.columns = ["Timestamp", "Unit", "Probability", "Risk Level", "Predicted Class", "Model"]
        st.dataframe(df_hist, width="stretch", hide_index=True, height=260)
