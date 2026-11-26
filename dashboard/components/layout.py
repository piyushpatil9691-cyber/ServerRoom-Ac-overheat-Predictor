"""Reusable industrial UI layout helpers for the Streamlit dashboard."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

import streamlit as st


def render_html(markup: str) -> None:
    """Render HTML cleanly via st.markdown without triggering CommonMark code blocks."""
    cleaned = " ".join(line.strip() for line in markup.splitlines() if line.strip())
    st.markdown(cleaned, unsafe_allow_html=True)


def format_timestamp(ts: str | None) -> str:
    if not ts:
        return "No data yet"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return ts


def status_badge_html(status_text: str, level: str = "info") -> str:
    """Render an accessible status badge using both color and explicit shape/label."""
    cls_map = {
        "ok": ("badge-ok", "●"),
        "operational": ("badge-ok", "●"),
        "low": ("badge-ok", "●"),
        "warning": ("badge-warn", "▲"),
        "warn": ("badge-warn", "▲"),
        "medium": ("badge-warn", "▲"),
        "high": ("badge-warn", "▲"),
        "acknowledged": ("badge-info", "◆"),
        "critical": ("badge-crit", "■"),
        "crit": ("badge-crit", "■"),
        "active": ("badge-crit", "■"),
        "offline": ("badge-crit", "■"),
        "resolved": ("badge-ok", "●"),
        "info": ("badge-info", "◆"),
    }
    css_cls, marker = cls_map.get(level.lower(), ("badge-info", "◆"))
    safe_text = html.escape(status_text)
    return f'<span class="badge {css_cls}">{marker} {safe_text}</span>'


def render_topbar(
    page_title: str,
    sys_status: dict[str, Any] | None,
    backend_ok: bool,
    selected_unit: str,
    operator_unlocked: bool,
) -> None:
    """Render top telemetry bar with connection status, timestamp, alert count, and unit."""
    summary = (sys_status or {}).get("summary", {})
    active_alerts = int(summary.get("active_alerts", 0))
    last_update = format_timestamp((sys_status or {}).get("last_data_update"))

    conn_badge = (
        status_badge_html("SYSTEM ONLINE", "ok")
        if backend_ok
        else status_badge_html("BACKEND OFFLINE", "crit")
    )
    alert_badge = (
        status_badge_html(f"ALERTS: {active_alerts} ACTIVE", "crit")
        if active_alerts > 0
        else status_badge_html("ALERTS: 0 ACTIVE", "ok")
    )
    op_badge = (
        status_badge_html("OPERATOR UNLOCKED", "info")
        if operator_unlocked
        else status_badge_html("VIEWER MODE", "info")
    )

    render_html(
        f"""
        <div class="topbar-wrap">
            <div>
                <h1 class="topbar-title">{html.escape(page_title)}</h1>
            </div>
            <div class="topbar-meta">
                <span>Unit Focus: <strong>{html.escape(selected_unit)}</strong></span>
                <span>Updated: <strong>{html.escape(last_update)}</strong></span>
                {conn_badge}
                {alert_badge}
                {op_badge}
            </div>
        </div>
        """
    )


def render_kpi_strip(items: list[dict[str, str]]) -> None:
    """Render a 4-column horizontal KPI summary strip without bloated cards."""
    cells_html = []
    for item in items:
        label = html.escape(str(item.get("label", "")))
        value = html.escape(str(item.get("value", "--")))
        sub = html.escape(str(item.get("sub", "")))
        accent_style = ""
        tone = item.get("tone")
        if tone == "crit":
            accent_style = ' style="color:#FF7B72;"'
        elif tone == "warn":
            accent_style = ' style="color:#E3B341;"'
        elif tone == "ok":
            accent_style = ' style="color:#56D364;"'

        cells_html.append(
            f'<div class="kpi-cell">'
            f'<div class="kpi-label">{label}</div>'
            f'<div class="kpi-value"{accent_style}>{value}</div>'
            f'<div class="kpi-sub">{sub}</div>'
            f'</div>'
        )
    render_html(f'<div class="kpi-strip">{"".join(cells_html)}</div>')


def render_section_header(title: str) -> None:
    render_html(f'<div class="section-header">{html.escape(title)}</div>')
