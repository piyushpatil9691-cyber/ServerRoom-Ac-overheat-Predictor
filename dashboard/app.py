"""Main Streamlit application entrypoint for Server Room AC Overheat Predictor."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.api_client import BackendClient
from dashboard.components.layout import render_html, render_topbar
from dashboard.views import (
    alert_center,
    email_settings,
    failure_prediction,
    live_monitoring,
    model_performance,
    overview,
    sensor_analytics,
    system_settings,
)

st.set_page_config(
    page_title="Server Room AC Overheat Predictor",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS_PATH = Path(__file__).resolve().parent / "styles" / "theme.css"
if CSS_PATH.exists():
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

NAV_SECTIONS = [
    "Overview",
    "Live Monitoring",
    "Failure Prediction",
    "Sensor Analytics",
    "Alert Center",
    "Model Performance",
    "Email Notification Settings",
    "System Settings",
]

LIVE_AUTO_REFRESH_PAGES = {
    "Overview",
    "Live Monitoring",
    "Failure Prediction",
    "Alert Center",
}


def main() -> None:
    client = BackendClient()
    if "operator_key" not in st.session_state:
        st.session_state["operator_key"] = ""
    if "operator_unlocked" not in st.session_state:
        st.session_state["operator_unlocked"] = False

    ok_sys, sys_status = client.get_system_status()
    ok_units, units = client.list_units()
    unit_options = ["All Units"] + [u["unit_id"] for u in units] if (ok_units and units) else ["All Units", "AC-01", "AC-02", "AC-03"]

    settings = (sys_status or {}).get("settings", {}) if ok_sys else {}
    refresh_seconds = max(1, int(float(settings.get("dashboard_refresh_seconds", "3"))))

    with st.sidebar:
        render_html(
            """
            <div class="sidebar-brand">
                <div class="sidebar-brand-title">CRAC TELEMETRY &amp; ML</div>
                <div class="sidebar-brand-sub">Server Room Overheat Predictor</div>
            </div>
            """
        )

        selected_page = st.radio(
            "Navigation",
            options=NAV_SECTIONS,
            index=0,
            key="nav_section",
        )

        render_html("<hr style='border-color:#232B36; margin:14px 0;'>")
        selected_unit = st.selectbox("AC Unit Scope", options=unit_options, index=0, key="unit_scope")
        auto_refresh = st.checkbox(f"Auto-refresh ({refresh_seconds}s)", value=True, key="auto_refresh_toggle")

        if st.session_state.get("operator_unlocked"):
            st.caption("Operator Session: Unlocked")
            if st.button("Lock Operator Session", width="stretch"):
                st.session_state["operator_key"] = ""
                st.session_state["operator_unlocked"] = False
                st.rerun()

    page_renderers = {
        "Overview": overview.render,
        "Live Monitoring": live_monitoring.render,
        "Failure Prediction": failure_prediction.render,
        "Sensor Analytics": sensor_analytics.render,
        "Alert Center": alert_center.render,
        "Model Performance": model_performance.render,
        "Email Notification Settings": email_settings.render,
        "System Settings": system_settings.render,
    }

    renderer = page_renderers[selected_page]
    operator_unlocked = bool(st.session_state.get("operator_unlocked"))

    if selected_page in LIVE_AUTO_REFRESH_PAGES and auto_refresh:
        @st.fragment(run_every=refresh_seconds)
        def _live_view() -> None:
            live_ok, live_status = client.get_system_status()
            render_topbar(
                page_title=selected_page,
                sys_status=live_status if live_ok else sys_status,
                backend_ok=live_ok,
                selected_unit=selected_unit,
                operator_unlocked=operator_unlocked,
            )
            renderer(client, selected_unit, live_status if live_ok else sys_status)

        _live_view()
    else:
        render_topbar(
            page_title=selected_page,
            sys_status=sys_status if ok_sys else None,
            backend_ok=ok_sys,
            selected_unit=selected_unit,
            operator_unlocked=operator_unlocked,
        )
        renderer(client, selected_unit, sys_status if ok_sys else None)


if __name__ == "__main__":
    main()
