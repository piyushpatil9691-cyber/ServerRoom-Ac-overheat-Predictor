"""System Settings page for thresholds, simulator controls, refresh cadence, and incident testing."""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

from dashboard.api_client import BackendClient
from dashboard.components.layout import render_html, render_section_header


def render(client: BackendClient, selected_unit: str, sys_status: dict[str, Any] | None) -> None:
    settings = (sys_status or {}).get("settings", {})
    ok_units, units = client.list_units()

    render_section_header("Operator Authorization")
    op_key = st.session_state.get("operator_key", "")
    with st.form("system_operator_unlock"):
        entered_key = st.text_input(
            "Operator Access Key",
            value="",
            type="password",
            placeholder="Enter OPERATOR_ACCESS_KEY to modify thresholds or simulator controls",
        )
        if st.form_submit_button("Verify Operator Access"):
            ok_auth, res_auth = client.verify_operator_key(entered_key)
            if ok_auth:
                st.session_state["operator_key"] = entered_key
                st.session_state["operator_unlocked"] = True
                st.success("Operator session authorized.")
                st.rerun()
            else:
                st.session_state["operator_unlocked"] = False
                st.error(f"Authorization failed: {res_auth}")

    c1, c2 = st.columns(2, gap="medium")

    with c1:
        render_section_header("Alert Engine & Telemetry Cadence")
        with st.form("system_settings_form"):
            alert_threshold = st.slider(
                "Failure Probability Alert Threshold",
                min_value=0.10,
                max_value=0.95,
                value=float(settings.get("alert_threshold", "0.70")),
                step=0.05,
                help="Triggers dashboard and email alerts when predicted 24h failure probability reaches this level.",
            )
            cooldown_min = st.number_input(
                "Notification Cooldown (Minutes)",
                min_value=1,
                max_value=1440,
                value=int(float(settings.get("alert_cooldown_minutes", "15"))),
            )
            sim_enabled = st.checkbox(
                "Continuous Sensor Simulator Enabled",
                value=str(settings.get("simulator_enabled", "true")).lower() == "true",
            )
            sim_interval = st.number_input(
                "Simulator Generation Interval (Seconds)",
                min_value=1,
                max_value=300,
                value=int(float(settings.get("simulator_interval_seconds", "3"))),
            )
            dash_refresh = st.number_input(
                "Dashboard Auto-Refresh Interval (Seconds)",
                min_value=1,
                max_value=60,
                value=int(float(settings.get("dashboard_refresh_seconds", "3"))),
            )

            if st.form_submit_button("Save System Settings", type="primary"):
                if not op_key:
                    st.error("Verify Operator Access above before updating system settings.")
                else:
                    ok_upd, res_upd = client.update_system_settings(
                        {
                            "alert_threshold": round(float(alert_threshold), 2),
                            "alert_cooldown_minutes": int(cooldown_min),
                            "simulator_enabled": bool(sim_enabled),
                            "simulator_interval_seconds": int(sim_interval),
                            "dashboard_refresh_seconds": int(dash_refresh),
                        },
                        operator_key=op_key,
                    )
                    if ok_upd:
                        st.success("System settings saved.")
                        st.rerun()
                    else:
                        st.error(f"Failed to save settings: {res_upd}")

    with c2:
        render_section_header("Controlled Unit Fault Simulation")
        st.caption(
            "Adjust an AC unit's simulated operating mode to demonstrate gradual degradation or "
            "trigger a controlled high-risk incident for end-to-end alert verification."
        )
        if ok_units and units:
            for u in units:
                uid = u["unit_id"]
                curr_mode = u.get("operating_mode", "normal")
                uc1, uc2, uc3 = st.columns([1.2, 1.2, 0.8])
                with uc1:
                    render_html(
                        f"<div><strong>{html.escape(uid)}</strong> ({html.escape(u['name'])})<br>"
                        f"<span style='color:#8B949E;font-size:0.78rem;'>Status: {html.escape(u['status'])}</span></div>"
                    )
                with uc2:
                    new_mode = st.selectbox(
                        f"Mode {uid}",
                        options=["normal", "degrading", "critical"],
                        index=["normal", "degrading", "critical"].index(curr_mode) if curr_mode in ("normal", "degrading", "critical") else 0,
                        key=f"mode_sel_{uid}",
                        label_visibility="collapsed",
                    )
                with uc3:
                    if st.button("Apply", key=f"mode_apply_{uid}", width="stretch"):
                        if not op_key:
                            st.error("Verify Operator Access first.")
                        else:
                            ok_m, res_m = client.set_unit_mode(uid, new_mode, operator_key=op_key)
                            if ok_m:
                                st.success(f"{uid} mode set to {new_mode}.")
                                st.rerun()
                            else:
                                st.error(str(res_m))

        st.divider()
        if st.button("Generate Immediate Sensor Tick Now", width="stretch"):
            if not op_key:
                st.error("Verify Operator Access first.")
            else:
                ok_tick, res_tick = client.trigger_simulate_tick(operator_key=op_key)
                if ok_tick:
                    st.success(f"Processed {res_tick.get('processed', 0)} sensor readings through ML & Alert Engine.")
                else:
                    st.error(str(res_tick))
