"""Custom-styled Plotly charts for industrial HVAC telemetry and ML evaluation."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

from ml.features import SENSOR_METADATA

PLOT_BG = "#121820"
PAPER_BG = "#121820"
GRID_COLOR = "#202833"
TEXT_COLOR = "#C9D1D9"
MUTED_COLOR = "#8B949E"
BLUE = "#388BFD"
CYAN = "#39C5CF"
GREEN = "#2EA043"
AMBER = "#D29922"
RED = "#F85149"


def _apply_industrial_layout(
    fig: go.Figure,
    title: str,
    y_title: str,
    height: int = 310,
    x_title: str = "",
) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#E6EDF3"), x=0.01, xanchor="left", y=0.96),
        height=height,
        margin=dict(l=54, r=18, t=64, b=38),
        paper_bgcolor=PAPER_BG,
        plot_bgcolor=PLOT_BG,
        font=dict(color=TEXT_COLOR, size=11),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="right",
            x=1.0,
            font=dict(size=10, color=MUTED_COLOR),
            bgcolor="rgba(0,0,0,0)",
        ),
        xaxis=dict(
            title=dict(text=x_title, font=dict(size=11, color=MUTED_COLOR)) if x_title else None,
            gridcolor=GRID_COLOR,
            zeroline=False,
            showline=True,
            linecolor=GRID_COLOR,
            tickfont=dict(color=MUTED_COLOR, size=10),
            automargin=True,
        ),
        yaxis=dict(
            title=dict(text=y_title, font=dict(size=11, color=MUTED_COLOR)) if y_title else None,
            gridcolor=GRID_COLOR,
            zeroline=False,
            showline=True,
            linecolor=GRID_COLOR,
            tickfont=dict(color=MUTED_COLOR, size=10),
            automargin=True,
        ),
    )
    return fig


def _prep_df(history: list[dict[str, Any]]) -> pd.DataFrame:
    if not history:
        return pd.DataFrame()
    df = pd.DataFrame(history)
    if "recorded_at" in df.columns:
        df["recorded_at_dt"] = pd.to_datetime(df["recorded_at"], format="ISO8601", errors="coerce")
        df = df.sort_values("recorded_at_dt")
    elif "predicted_at" in df.columns:
        df["predicted_at_dt"] = pd.to_datetime(df["predicted_at"], format="ISO8601", errors="coerce")
        df = df.sort_values("predicted_at_dt")
    return df


def room_temperature_chart(history: list[dict[str, Any]], height: int = 320) -> go.Figure:
    df = _prep_df(history)
    fig = go.Figure()
    if not df.empty:
        for unit_id, grp in df.groupby("unit_id"):
            fig.add_trace(
                go.Scatter(
                    x=grp["recorded_at_dt"],
                    y=grp["room_temp"],
                    mode="lines",
                    name=str(unit_id),
                    line=dict(width=2),
                    hovertemplate="%{y:.2f} °C<extra>%{fullData.name}</extra>",
                )
            )
    warn_val = SENSOR_METADATA["room_temp"]["warning_high"]
    crit_val = SENSOR_METADATA["room_temp"]["critical_high"]
    fig.add_hline(y=warn_val, line_dash="dash", line_color=AMBER, line_width=1.2, annotation_text=f"Warn {warn_val}°C")
    fig.add_hline(y=crit_val, line_dash="dot", line_color=RED, line_width=1.2, annotation_text=f"Crit {crit_val}°C")
    return _apply_industrial_layout(fig, "Server Room Ambient Temperature Trend", "Temperature (°C)", height=height)


def inlet_outlet_comparison_chart(history: list[dict[str, Any]], height: int = 320) -> go.Figure:
    df = _prep_df(history)
    fig = go.Figure()
    if not df.empty:
        fig.add_trace(
            go.Scatter(
                x=df["recorded_at_dt"],
                y=df["ac_inlet_temp"],
                mode="lines",
                name="AC Inlet (Return)",
                line=dict(color=AMBER, width=2),
                hovertemplate="%{y:.2f} °C<extra>AC Inlet</extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["recorded_at_dt"],
                y=df["ac_outlet_temp"],
                mode="lines",
                name="AC Outlet (Supply)",
                line=dict(color=CYAN, width=2),
                hovertemplate="%{y:.2f} °C<extra>AC Outlet</extra>",
            )
        )
        delta_t = df["ac_inlet_temp"] - df["ac_outlet_temp"]
        fig.add_trace(
            go.Scatter(
                x=df["recorded_at_dt"],
                y=delta_t,
                mode="lines",
                name="Cooling Delta-T",
                line=dict(color=GREEN, width=1.6, dash="dash"),
                hovertemplate="%{y:.2f} °C<extra>Delta-T</extra>",
            )
        )
    fig.add_hline(
        y=SENSOR_METADATA["ac_outlet_temp"]["warning_high"],
        line_dash="dot",
        line_color=RED,
        line_width=1.0,
        annotation_text="Outlet Warn 18°C",
    )
    return _apply_industrial_layout(fig, "AC Inlet vs. Outlet & Cooling Delta-T", "Temperature (°C)", height=height)


def humidity_chart(history: list[dict[str, Any]], height: int = 280) -> go.Figure:
    df = _prep_df(history)
    fig = go.Figure()
    if not df.empty:
        fig.add_hrect(
            y0=SENSOR_METADATA["humidity"]["normal_min"],
            y1=SENSOR_METADATA["humidity"]["normal_max"],
            fillcolor="rgba(46, 160, 67, 0.08)",
            line_width=0,
            annotation_text="Acceptable Range (35-60%)",
            annotation_position="top left",
        )
        for unit_id, grp in df.groupby("unit_id"):
            fig.add_trace(
                go.Scatter(
                    x=grp["recorded_at_dt"],
                    y=grp["humidity"],
                    mode="lines",
                    name=str(unit_id),
                    line=dict(width=2),
                    hovertemplate="%{y:.1f} % RH<extra>%{fullData.name}</extra>",
                )
            )
    fig.add_hline(y=SENSOR_METADATA["humidity"]["warning_high"], line_dash="dash", line_color=AMBER, line_width=1.1)
    return _apply_industrial_layout(fig, "Relative Humidity Trend", "Humidity (% RH)", height=height)


def compressor_current_chart(history: list[dict[str, Any]], height: int = 280) -> go.Figure:
    df = _prep_df(history)
    fig = go.Figure()
    if not df.empty:
        for unit_id, grp in df.groupby("unit_id"):
            fig.add_trace(
                go.Scatter(
                    x=grp["recorded_at_dt"],
                    y=grp["compressor_current"],
                    mode="lines",
                    name=str(unit_id),
                    line=dict(width=2),
                    hovertemplate="%{y:.2f} A<extra>%{fullData.name}</extra>",
                )
            )
    warn_c = SENSOR_METADATA["compressor_current"]["warning_high"]
    crit_c = SENSOR_METADATA["compressor_current"]["critical_high"]
    fig.add_hline(y=warn_c, line_dash="dash", line_color=AMBER, line_width=1.1, annotation_text=f"Warn {warn_c}A")
    fig.add_hline(y=crit_c, line_dash="dot", line_color=RED, line_width=1.1, annotation_text=f"Crit {crit_c}A")
    return _apply_industrial_layout(fig, "Compressor Electrical Current", "Current (Amps)", height=height)


def fan_speed_chart(history: list[dict[str, Any]], height: int = 280) -> go.Figure:
    df = _prep_df(history)
    fig = go.Figure()
    if not df.empty:
        for unit_id, grp in df.groupby("unit_id"):
            fig.add_trace(
                go.Scatter(
                    x=grp["recorded_at_dt"],
                    y=grp["fan_speed"],
                    mode="lines",
                    name=str(unit_id),
                    line=dict(width=2),
                    hovertemplate="%{y:.0f} RPM<extra>%{fullData.name}</extra>",
                )
            )
    warn_f = SENSOR_METADATA["fan_speed"]["warning_low"]
    crit_f = SENSOR_METADATA["fan_speed"]["critical_low"]
    fig.add_hline(y=warn_f, line_dash="dash", line_color=AMBER, line_width=1.1, annotation_text=f"Warn <{warn_f} RPM")
    fig.add_hline(y=crit_f, line_dash="dot", line_color=RED, line_width=1.1, annotation_text=f"Crit <{crit_f} RPM")
    return _apply_industrial_layout(fig, "Evaporator / Condenser Fan Speed", "Speed (RPM)", height=height)


def failure_probability_gauge(probability: float, threshold: float = 0.70, unit_id: str = "AC-01") -> go.Figure:
    pct = round(probability * 100.0, 1)
    bar_color = RED if probability >= 0.90 else (AMBER if probability >= threshold else (BLUE if probability >= 0.40 else GREEN))
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=pct,
            number={"suffix": "%", "font": {"size": 34, "color": "#E6EDF3"}},
            title={"text": f"{unit_id} — 24h Failure Risk", "font": {"size": 13, "color": MUTED_COLOR}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": MUTED_COLOR, "tickfont": {"size": 10}},
                "bar": {"color": bar_color, "thickness": 0.30},
                "bgcolor": "#161E28",
                "borderwidth": 1,
                "bordercolor": "#232B36",
                "steps": [
                    {"range": [0, 40], "color": "rgba(46, 160, 67, 0.12)"},
                    {"range": [40, 70], "color": "rgba(56, 139, 253, 0.12)"},
                    {"range": [70, 90], "color": "rgba(210, 153, 34, 0.14)"},
                    {"range": [90, 100], "color": "rgba(248, 81, 73, 0.18)"},
                ],
                "threshold": {
                    "line": {"color": "#E6EDF3", "width": 2},
                    "thickness": 0.85,
                    "value": round(threshold * 100.0, 1),
                },
            },
        )
    )
    fig.update_layout(
        height=240,
        margin=dict(l=20, r=20, t=40, b=10),
        paper_bgcolor=PAPER_BG,
        font=dict(color=TEXT_COLOR),
    )
    return fig


def prediction_probability_trend_chart(
    pred_history: list[dict[str, Any]],
    threshold: float = 0.70,
    height: int = 280,
) -> go.Figure:
    df = _prep_df(pred_history)
    fig = go.Figure()
    if not df.empty:
        df["prob_pct"] = df["failure_probability"] * 100.0
        for unit_id, grp in df.groupby("unit_id"):
            fig.add_trace(
                go.Scatter(
                    x=grp["predicted_at_dt"],
                    y=grp["prob_pct"],
                    mode="lines",
                    name=str(unit_id),
                    line=dict(width=2),
                    hovertemplate="%{y:.1f}%<extra>%{fullData.name}</extra>",
                )
            )
    fig.add_hline(
        y=round(threshold * 100.0, 1),
        line_dash="dash",
        line_color=RED,
        line_width=1.2,
        annotation_text=f"Alert Threshold ({threshold*100:.0f}%)",
    )
    return _apply_industrial_layout(fig, "Predicted 24h Failure Probability Timeline", "Probability (%)", height=height)


def confusion_matrix_chart(cm_data: dict[str, Any]) -> go.Figure:
    z = cm_data["matrix"]
    labels = cm_data.get("labels", ["No Failure (0)", "Failure <=24h (1)"])
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=[f"Pred: {l}" for l in labels],
            y=[f"Actual: {l}" for l in labels],
            text=[[str(val) for val in row] for row in z],
            texttemplate="%{text}",
            textfont={"size": 16, "color": "#FFFFFF"},
            colorscale=[[0.0, "#161E28"], [1.0, "#1F6FEB"]],
            showscale=False,
        )
    )
    fig.update_layout(
        title=dict(text="Confusion Matrix (Test Holdout Split)", font=dict(size=13, color="#E6EDF3"), x=0.01),
        height=310,
        margin=dict(l=20, r=20, t=50, b=40),
        paper_bgcolor=PAPER_BG,
        plot_bgcolor=PLOT_BG,
        font=dict(color=TEXT_COLOR, size=11),
        xaxis=dict(automargin=True, tickfont=dict(color=MUTED_COLOR, size=10)),
        yaxis=dict(autorange="reversed", automargin=True, tickfont=dict(color=MUTED_COLOR, size=10)),
    )
    return fig


def feature_importance_chart(importances: list[dict[str, Any]]) -> go.Figure:
    ordered = sorted(importances, key=lambda x: x["importance"])
    labels = [SENSOR_METADATA.get(item["feature"], {}).get("label", item["feature"]) for item in ordered]
    values = [round(float(item["importance"]) * 100.0, 2) for item in ordered]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=BLUE,
            hovertemplate="%{x:.2f}%<extra>%{y}</extra>",
        )
    )
    return _apply_industrial_layout(
        fig,
        "Random Forest Feature Importance",
        y_title="",
        x_title="Relative Weight (%)",
        height=310,
    )
