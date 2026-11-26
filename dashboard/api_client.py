"""HTTP client for communicating with the FastAPI backend."""

from __future__ import annotations

import os
from typing import Any

import requests

from config import get_settings


class BackendClient:
    """Thin wrapper around FastAPI REST endpoints."""

    def __init__(self, base_url: str | None = None, timeout: float = 8.0) -> None:
        settings = get_settings()
        self.base_url = (base_url or os.environ.get("API_BASE_URL") or settings.api_base_url).rstrip("/")
        self.timeout = timeout

    def _headers(self, operator_key: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if operator_key:
            headers["X-Operator-Key"] = operator_key
        return headers

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        operator_key: str | None = None,
    ) -> tuple[bool, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=self._headers(operator_key),
                timeout=self.timeout,
            )
            if resp.ok:
                return True, resp.json()
            try:
                err_detail = resp.json().get("detail", resp.text)
            except Exception:
                err_detail = resp.text
            return False, f"HTTP {resp.status_code}: {err_detail}"
        except requests.RequestException as exc:
            return False, f"Connection error: {exc}"

    def get_health(self) -> tuple[bool, Any]:
        return self._request("GET", "/api/v1/system/health")

    def get_system_status(self) -> tuple[bool, Any]:
        return self._request("GET", "/api/v1/system/status")

    def verify_operator_key(self, operator_key: str) -> tuple[bool, Any]:
        return self._request("POST", "/api/v1/system/auth/verify", operator_key=operator_key)

    def update_system_settings(self, payload: dict[str, Any], operator_key: str) -> tuple[bool, Any]:
        return self._request("PUT", "/api/v1/system/settings", json_body=payload, operator_key=operator_key)

    def list_units(self) -> tuple[bool, Any]:
        return self._request("GET", "/api/v1/units")

    def get_unit_status(self, unit_id: str) -> tuple[bool, Any]:
        return self._request("GET", f"/api/v1/units/{unit_id}/status")

    def set_unit_mode(self, unit_id: str, operating_mode: str, operator_key: str) -> tuple[bool, Any]:
        return self._request(
            "PUT",
            f"/api/v1/units/{unit_id}/mode",
            json_body={"operating_mode": operating_mode},
            operator_key=operator_key,
        )

    def get_latest_sensors(self, unit_id: str | None = None) -> tuple[bool, Any]:
        params = {"unit_id": unit_id} if unit_id else None
        return self._request("GET", "/api/v1/sensors/latest", params=params)

    def get_sensor_history(
        self,
        unit_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 200,
    ) -> tuple[bool, Any]:
        params: dict[str, Any] = {"limit": limit}
        if unit_id:
            params["unit_id"] = unit_id
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        return self._request("GET", "/api/v1/sensors/history", params=params)

    def get_sensor_drift(self, unit_id: str | None = None, window: int = 20) -> tuple[bool, Any]:
        params: dict[str, Any] = {"window": window}
        if unit_id:
            params["unit_id"] = unit_id
        return self._request("GET", "/api/v1/sensors/drift", params=params)

    def get_data_quality(self, unit_id: str | None = None, limit: int = 100) -> tuple[bool, Any]:
        params: dict[str, Any] = {"limit": limit}
        if unit_id:
            params["unit_id"] = unit_id
        return self._request("GET", "/api/v1/sensors/quality", params=params)

    def trigger_simulate_tick(self, operator_key: str) -> tuple[bool, Any]:
        return self._request("POST", "/api/v1/sensors/simulate-tick", operator_key=operator_key)

    def get_latest_predictions(self, unit_id: str | None = None) -> tuple[bool, Any]:
        params = {"unit_id": unit_id} if unit_id else None
        return self._request("GET", "/api/v1/predictions/latest", params=params)

    def get_prediction_history(self, unit_id: str | None = None, limit: int = 200) -> tuple[bool, Any]:
        params: dict[str, Any] = {"limit": limit}
        if unit_id:
            params["unit_id"] = unit_id
        return self._request("GET", "/api/v1/predictions/history", params=params)

    def get_model_performance(self) -> tuple[bool, Any]:
        return self._request("GET", "/api/v1/model/performance")

    def list_alerts(
        self,
        status: str | None = None,
        severity: str | None = None,
        unit_id: str | None = None,
        limit: int = 200,
    ) -> tuple[bool, Any]:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if severity:
            params["severity"] = severity
        if unit_id:
            params["unit_id"] = unit_id
        return self._request("GET", "/api/v1/alerts", params=params)

    def acknowledge_alert(self, alert_id: int, actor: str = "operator", notes: str = "") -> tuple[bool, Any]:
        return self._request(
            "POST",
            f"/api/v1/alerts/{alert_id}/acknowledge",
            json_body={"actor": actor, "notes": notes},
        )

    def resolve_alert(self, alert_id: int, actor: str = "operator", notes: str = "") -> tuple[bool, Any]:
        return self._request(
            "POST",
            f"/api/v1/alerts/{alert_id}/resolve",
            json_body={"actor": actor, "notes": notes},
        )

    def get_email_config(self) -> tuple[bool, Any]:
        return self._request("GET", "/api/v1/email/config")

    def save_email_config(self, payload: dict[str, Any], operator_key: str) -> tuple[bool, Any]:
        return self._request("PUT", "/api/v1/email/config", json_body=payload, operator_key=operator_key)

    def toggle_email_notifications(self, enabled: bool, operator_key: str) -> tuple[bool, Any]:
        return self._request(
            "PATCH",
            "/api/v1/email/toggle",
            json_body={"enabled": enabled},
            operator_key=operator_key,
        )

    def test_email_connection(self, operator_key: str) -> tuple[bool, Any]:
        return self._request("POST", "/api/v1/email/test", operator_key=operator_key)
