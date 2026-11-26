"""Email Notification Settings page for secure Gmail SMTP + App Password setup."""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

from dashboard.api_client import BackendClient
from dashboard.components.layout import format_timestamp, render_html, render_section_header, status_badge_html


def render(client: BackendClient, selected_unit: str, sys_status: dict[str, Any] | None) -> None:
    ok_cfg, cfg = client.get_email_config()
    if not ok_cfg:
        st.error(f"Unable to fetch email configuration: {cfg}")
        return

    enc_ok = bool(cfg.get("encryption_key_configured"))
    is_configured = bool(cfg.get("is_configured"))
    enabled = bool(cfg.get("enabled"))

    status_label = (
        "ENABLED & CONFIGURED"
        if (is_configured and enabled)
        else ("CONFIGURED (PAUSED)" if is_configured else "INCOMPLETE CONFIGURATION")
    )
    status_tone = "ok" if (is_configured and enabled) else ("warn" if is_configured else "crit")

    col_status, col_guide = st.columns([1.25, 1.0], gap="medium")

    with col_status:
        render_section_header("SMTP Delivery Status")
        last_test_block = ""
        if cfg.get("last_test_message"):
            last_test_block = (
                f'<div style="font-size:0.78rem; color:#8B949E; margin-top:6px;">'
                f'Last Test Output: {html.escape(cfg["last_test_message"])}</div>'
            )

        render_html(
            f"""
            <div class="panel">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span>Notification Pipeline</span>
                    {status_badge_html(status_label, status_tone)}
                </div>
                <div style="font-size:0.82rem; color:#C9D1D9; margin-top:10px;">
                    <div>Encryption Key (Env): <strong>{'Configured (Fernet)' if enc_ok else 'Missing CREDENTIALS_ENCRYPTION_KEY'}</strong></div>
                    <div>Stored App Password: <strong>{html.escape(cfg.get('password_masked', 'Not configured'))}</strong></div>
                    <div>Last Test Status: <strong>{html.escape(str(cfg.get('last_test_status') or 'Never tested').upper())}</strong>
                        ({html.escape(format_timestamp(cfg.get('last_test_at')))})</div>
                </div>
                {last_test_block}
            </div>
            """
        )

        if not enc_ok:
            st.warning(
                "CREDENTIALS_ENCRYPTION_KEY is not configured in the backend environment. "
                "Set a valid Fernet key in `.env` before saving SMTP credentials."
            )

        render_section_header("Operator Authorization")
        op_key = st.session_state.get("operator_key", "")
        with st.form("email_operator_unlock"):
            entered_key = st.text_input(
                "Operator Access Key",
                value="",
                type="password",
                placeholder="Enter OPERATOR_ACCESS_KEY to modify or test SMTP settings",
            )
            unlock_btn = st.form_submit_button("Verify Operator Access")
            if unlock_btn:
                ok_auth, res_auth = client.verify_operator_key(entered_key)
                if ok_auth:
                    st.session_state["operator_key"] = entered_key
                    st.session_state["operator_unlocked"] = True
                    st.success("Operator session authorized for configuration changes.")
                    st.rerun()
                else:
                    st.session_state["operator_unlocked"] = False
                    st.error(f"Authorization failed: {res_auth}")

        render_section_header("Gmail SMTP Configuration")
        with st.form("gmail_smtp_config_form"):
            sender_email = st.text_input(
                "Sender Gmail Address",
                value=cfg.get("sender_email", ""),
                placeholder="alerts.facility@gmail.com",
            )
            app_password = st.text_input(
                "Gmail App Password (16-character Google App Password)",
                value="",
                type="password",
                placeholder=(
                    "Leave blank to keep existing encrypted password"
                    if cfg.get("has_app_password")
                    else "Enter 16-character Google App Password"
                ),
            )
            recipient_email = st.text_input(
                "Maintenance Recipient Email",
                value=cfg.get("recipient_email", ""),
                placeholder="oncall.datacenter@example.com",
            )
            c_host, c_port = st.columns([1.4, 0.8])
            with c_host:
                smtp_host = st.text_input("SMTP Host", value=cfg.get("smtp_host", "smtp.gmail.com"))
            with c_port:
                smtp_port = st.number_input("SMTP Port", min_value=1, max_value=65535, value=int(cfg.get("smtp_port", 587)))

            c_tls, c_en = st.columns(2)
            with c_tls:
                use_starttls = st.checkbox("Use STARTTLS (Recommended for Port 587)", value=bool(cfg.get("use_starttls", True)))
            with c_en:
                enable_alerts = st.checkbox("Enable Email Alert Notifications", value=bool(cfg.get("enabled", False)))

            save_btn = st.form_submit_button("Save Configuration", type="primary")
            if save_btn:
                if not op_key:
                    st.error("Verify Operator Access above before saving SMTP settings.")
                else:
                    payload = {
                        "sender_email": sender_email.strip(),
                        "app_password": app_password.strip() if app_password.strip() else None,
                        "recipient_email": recipient_email.strip(),
                        "smtp_host": smtp_host.strip(),
                        "smtp_port": int(smtp_port),
                        "use_starttls": use_starttls,
                        "enabled": enable_alerts,
                    }
                    ok_save, res_save = client.save_email_config(payload, operator_key=op_key)
                    if ok_save:
                        st.success("Encrypted Gmail SMTP configuration saved persistently.")
                        st.rerun()
                    else:
                        st.error(f"Failed to save SMTP configuration: {res_save}")

        btn_c1, btn_c2 = st.columns(2)
        with btn_c1:
            if st.button("Test Email Connection", width="stretch"):
                if not op_key:
                    st.error("Verify Operator Access above before sending a test email.")
                else:
                    with st.spinner("Connecting to Gmail SMTP via STARTTLS..."):
                        ok_test, res_test = client.test_email_connection(operator_key=op_key)
                    if ok_test and isinstance(res_test, dict) and res_test.get("success"):
                        st.success(res_test.get("message", "Test email sent."))
                    else:
                        msg = res_test.get("message") if isinstance(res_test, dict) else str(res_test)
                        st.error(msg or "Test email failed.")
        with btn_c2:
            toggle_label = "Disable Email Alerts" if enabled else "Enable Email Alerts"
            if st.button(toggle_label, width="stretch"):
                if not op_key:
                    st.error("Verify Operator Access above before toggling notifications.")
                else:
                    ok_tog, res_tog = client.toggle_email_notifications(not enabled, operator_key=op_key)
                    if ok_tog:
                        st.success(f"Email notifications {'enabled' if not enabled else 'disabled'}.")
                        st.rerun()
                    else:
                        st.error(str(res_tog))

    with col_guide:
        render_section_header("Google App Password Setup Guide")
        render_html(
            """
            <div class="panel" style="font-size:0.84rem; line-height:1.55; color:#C9D1D9;">
                <p style="margin-top:0;"><strong>Never use your standard Gmail login password.</strong> Google blocks basic password SMTP logins; generate a dedicated App Password instead:</p>
                <ol style="padding-left:18px; margin-bottom:10px;">
                    <li>Sign in to the sender <strong>Gmail account</strong>.</li>
                    <li>Enable <strong>Google 2-Step Verification</strong> under Security settings.</li>
                    <li>Open <strong>App Passwords</strong> in Google Account Security and create a new password (e.g., named <em>ServerRoomACPredictor</em>).</li>
                    <li>Enter the <strong>Sender Gmail Address</strong> on the left.</li>
                    <li>Paste the generated <strong>16-character App Password</strong> (spaces optional).</li>
                    <li>Enter the <strong>Maintenance Recipient Email</strong> address.</li>
                    <li>Click <strong>Save Configuration</strong> (stored using Fernet encryption).</li>
                    <li>Click <strong>Test Email Connection</strong> to verify STARTTLS delivery.</li>
                </ol>
                <p style="margin-bottom:0; color:#8B949E; font-size:0.78rem;">
                    Security Notice: Credentials are encrypted at rest in SQLite using the external
                    <code>CREDENTIALS_ENCRYPTION_KEY</code> environment variable and are never returned by APIs,
                    written to logs, or displayed in the dashboard after saving.
                </p>
            </div>
            """
        )
