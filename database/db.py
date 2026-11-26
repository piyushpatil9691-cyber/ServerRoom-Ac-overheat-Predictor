"""SQLite database initialization and data access helpers."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from config import get_settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

DEFAULT_AC_UNITS = [
    ("AC-01", "CRAC Unit Alpha", "Server Hall A - North Rack Row", 35.0, "operational", "normal"),
    ("AC-02", "CRAC Unit Beta", "Server Hall A - South Rack Row", 35.0, "operational", "normal"),
    ("AC-03", "CRAC Unit Gamma", "Core Network & Storage Cage", 25.0, "operational", "normal"),
]

DEFAULT_SYSTEM_SETTINGS = {
    "alert_threshold": "0.70",
    "alert_cooldown_minutes": "15",
    "simulator_enabled": "true",
    "simulator_interval_seconds": "3",
    "dashboard_refresh_seconds": "3",
}


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DatabaseManager:
    """Clean SQLite access layer with WAL mode and explicit connection handling."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        settings = get_settings()
        raw_path = Path(db_path) if db_path is not None else settings.resolved_path(settings.database_path)
        self.db_path = raw_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured SQLite connection that commits or rolls back cleanly."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("BEGIN;")
            yield conn
            conn.execute("COMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK;")
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Create schema tables, indexes, and seed default records."""
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        now = utc_now_iso()

        conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.executescript(schema_sql)
            conn.commit()
        finally:
            conn.close()

        settings = get_settings()
        defaults = dict(DEFAULT_SYSTEM_SETTINGS)
        defaults["alert_threshold"] = f"{settings.alert_threshold:.2f}"
        defaults["alert_cooldown_minutes"] = str(settings.alert_cooldown_minutes)
        defaults["simulator_enabled"] = "true" if settings.simulator_enabled else "false"
        defaults["simulator_interval_seconds"] = str(settings.simulator_interval_seconds)
        defaults["dashboard_refresh_seconds"] = str(settings.dashboard_refresh_seconds)

        with self.connection() as conn:
            for unit_id, name, location, cap_kw, status, mode in DEFAULT_AC_UNITS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO ac_units
                    (unit_id, name, location, rated_capacity_kw, status, operating_mode, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (unit_id, name, location, cap_kw, status, mode, now, now),
                )

            conn.execute(
                """
                INSERT OR IGNORE INTO email_settings
                (id, sender_email, encrypted_app_password, recipient_email, smtp_host, smtp_port, use_starttls, enabled, updated_at)
                VALUES (1, '', '', '', 'smtp.gmail.com', 587, 1, 0, ?)
                """,
                (now,),
            )

            for key, value in defaults.items():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO system_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (key, value, now),
                )

    # ------------------------------------------------------------------
    # AC Units
    # ------------------------------------------------------------------
    def list_ac_units(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM ac_units ORDER BY unit_id ASC").fetchall()
            return [dict(r) for r in rows]

    def get_ac_unit(self, unit_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM ac_units WHERE unit_id = ?", (unit_id,)).fetchone()
            return dict(row) if row else None

    def update_ac_unit_status(
        self, unit_id: str, status: str | None = None, operating_mode: str | None = None
    ) -> dict[str, Any] | None:
        now = utc_now_iso()
        with self.connection() as conn:
            existing = conn.execute("SELECT * FROM ac_units WHERE unit_id = ?", (unit_id,)).fetchone()
            if not existing:
                return None
            new_status = status if status is not None else existing["status"]
            new_mode = operating_mode if operating_mode is not None else existing["operating_mode"]
            conn.execute(
                """
                UPDATE ac_units SET status = ?, operating_mode = ?, updated_at = ?
                WHERE unit_id = ?
                """,
                (new_status, new_mode, now, unit_id),
            )
            row = conn.execute("SELECT * FROM ac_units WHERE unit_id = ?", (unit_id,)).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Sensor Readings
    # ------------------------------------------------------------------
    def insert_sensor_reading(self, payload: dict[str, Any]) -> int:
        recorded_at = payload.get("recorded_at") or utc_now_iso()
        missing_fields = payload.get("missing_fields") or []
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO sensor_readings (
                    unit_id, recorded_at, room_temp, ac_outlet_temp, ac_inlet_temp,
                    humidity, compressor_current, fan_speed,
                    is_missing_any, missing_fields, quality_status, quality_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["unit_id"],
                    recorded_at,
                    payload.get("room_temp"),
                    payload.get("ac_outlet_temp"),
                    payload.get("ac_inlet_temp"),
                    payload.get("humidity"),
                    payload.get("compressor_current"),
                    payload.get("fan_speed"),
                    1 if payload.get("is_missing_any") else 0,
                    json.dumps(missing_fields),
                    payload.get("quality_status", "ok"),
                    payload.get("quality_notes", ""),
                ),
            )
            if cur.lastrowid and cur.rowcount > 0:
                return int(cur.lastrowid)
            row = conn.execute(
                "SELECT id FROM sensor_readings WHERE unit_id = ? AND recorded_at = ?",
                (payload["unit_id"], recorded_at),
            ).fetchone()
            return int(row["id"]) if row else 0

    def get_latest_sensor_readings(self, unit_id: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if unit_id:
                rows = conn.execute(
                    """
                    SELECT * FROM sensor_readings
                    WHERE unit_id = ?
                    ORDER BY recorded_at DESC, id DESC
                    LIMIT 1
                    """,
                    (unit_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT sr.* FROM sensor_readings sr
                    INNER JOIN (
                        SELECT unit_id, MAX(id) AS max_id
                        FROM sensor_readings
                        GROUP BY unit_id
                    ) latest ON sr.id = latest.max_id
                    ORDER BY sr.unit_id ASC
                    """
                ).fetchall()
            return [self._deserialize_reading(dict(r)) for r in rows]

    def get_sensor_history(
        self,
        unit_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if unit_id:
            clauses.append("unit_id = ?")
            params.append(unit_id)
        if start_time:
            clauses.append("recorded_at >= ?")
            params.append(start_time)
        if end_time:
            clauses.append("recorded_at <= ?")
            params.append(end_time)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT * FROM sensor_readings
            {where_sql}
            ORDER BY recorded_at DESC, id DESC
            LIMIT ?
        """
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._deserialize_reading(dict(r)) for r in rows]

    @staticmethod
    def _deserialize_reading(row: dict[str, Any]) -> dict[str, Any]:
        row["is_missing_any"] = bool(row.get("is_missing_any"))
        raw_mf = row.get("missing_fields")
        if isinstance(raw_mf, str):
            try:
                row["missing_fields"] = json.loads(raw_mf)
            except json.JSONDecodeError:
                row["missing_fields"] = []
        return row

    # ------------------------------------------------------------------
    # Predictions
    # ------------------------------------------------------------------
    def insert_prediction(self, payload: dict[str, Any]) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO predictions (
                    unit_id, reading_id, predicted_at, failure_probability,
                    predicted_class, risk_level, contributing_factors, model_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["unit_id"],
                    payload.get("reading_id"),
                    payload.get("predicted_at") or utc_now_iso(),
                    float(payload["failure_probability"]),
                    int(payload["predicted_class"]),
                    payload["risk_level"],
                    json.dumps(payload.get("contributing_factors", [])),
                    payload.get("model_version", "rf-v1"),
                ),
            )
            return int(cur.lastrowid)

    def get_latest_predictions(self, unit_id: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if unit_id:
                rows = conn.execute(
                    """
                    SELECT * FROM predictions
                    WHERE unit_id = ?
                    ORDER BY predicted_at DESC, id DESC
                    LIMIT 1
                    """,
                    (unit_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT p.* FROM predictions p
                    INNER JOIN (
                        SELECT unit_id, MAX(id) AS max_id
                        FROM predictions
                        GROUP BY unit_id
                    ) latest ON p.id = latest.max_id
                    ORDER BY p.unit_id ASC
                    """
                ).fetchall()
            return [self._deserialize_prediction(dict(r)) for r in rows]

    def get_prediction_history(
        self,
        unit_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if unit_id:
                rows = conn.execute(
                    """
                    SELECT * FROM predictions
                    WHERE unit_id = ?
                    ORDER BY predicted_at DESC, id DESC
                    LIMIT ?
                    """,
                    (unit_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM predictions
                    ORDER BY predicted_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [self._deserialize_prediction(dict(r)) for r in rows]

    @staticmethod
    def _deserialize_prediction(row: dict[str, Any]) -> dict[str, Any]:
        raw_cf = row.get("contributing_factors")
        if isinstance(raw_cf, str):
            try:
                row["contributing_factors"] = json.loads(raw_cf)
            except json.JSONDecodeError:
                row["contributing_factors"] = []
        return row

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------
    def get_open_alert_for_unit(self, unit_id: str) -> dict[str, Any] | None:
        """Return currently open ('active' or 'acknowledged') alert for a unit."""
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM alerts
                WHERE unit_id = ? AND status IN ('active', 'acknowledged')
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (unit_id,),
            ).fetchone()
            return self._deserialize_alert(dict(row)) if row else None

    def get_last_alert_for_unit(self, unit_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM alerts
                WHERE unit_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (unit_id,),
            ).fetchone()
            return self._deserialize_alert(dict(row)) if row else None

    def insert_alert(self, payload: dict[str, Any]) -> int:
        now = payload.get("created_at") or utc_now_iso()
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO alerts (
                    unit_id, prediction_id, failure_probability, risk_level, severity,
                    status, title, description, recommended_action, triggering_readings,
                    created_at, email_delivery_status, email_error, last_notified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["unit_id"],
                    payload.get("prediction_id"),
                    float(payload["failure_probability"]),
                    payload["risk_level"],
                    payload["severity"],
                    payload.get("status", "active"),
                    payload["title"],
                    payload["description"],
                    payload["recommended_action"],
                    json.dumps(payload.get("triggering_readings", {})),
                    now,
                    payload.get("email_delivery_status", "pending"),
                    payload.get("email_error"),
                    payload.get("last_notified_at"),
                ),
            )
            alert_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO alert_status_history (alert_id, old_status, new_status, changed_by, notes, changed_at)
                VALUES (?, NULL, ?, 'alert_engine', 'Alert created from threshold exceedance', ?)
                """,
                (alert_id, payload.get("status", "active"), now),
            )
            return alert_id

    def update_alert_notification(
        self,
        alert_id: int,
        email_delivery_status: str,
        email_error: str | None = None,
        last_notified_at: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE alerts
                SET email_delivery_status = ?,
                    email_error = ?,
                    last_notified_at = COALESCE(?, last_notified_at)
                WHERE id = ?
                """,
                (email_delivery_status, email_error, last_notified_at, alert_id),
            )

    def update_open_alert_snapshot(
        self,
        alert_id: int,
        failure_probability: float,
        risk_level: str,
        severity: str,
        triggering_readings: dict[str, Any],
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE alerts
                SET failure_probability = ?, risk_level = ?, severity = ?, triggering_readings = ?
                WHERE id = ?
                """,
                (
                    float(failure_probability),
                    risk_level,
                    severity,
                    json.dumps(triggering_readings),
                    alert_id,
                ),
            )

    def list_alerts(
        self,
        status: str | None = None,
        severity: str | None = None,
        unit_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            if status == "open":
                clauses.append("status IN ('active', 'acknowledged')")
            else:
                clauses.append("status = ?")
                params.append(status)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if unit_id:
            clauses.append("unit_id = ?")
            params.append(unit_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM alerts {where_sql} ORDER BY created_at DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
            return [self._deserialize_alert(dict(r)) for r in rows]

    def get_alert(self, alert_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            return self._deserialize_alert(dict(row)) if row else None

    def transition_alert_status(
        self,
        alert_id: int,
        new_status: str,
        actor: str = "operator",
        notes: str = "",
    ) -> dict[str, Any] | None:
        now = utc_now_iso()
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if not row:
                return None
            old_status = row["status"]
            if new_status == "acknowledged":
                conn.execute(
                    """
                    UPDATE alerts
                    SET status = 'acknowledged', acknowledged_at = ?, acknowledged_by = ?
                    WHERE id = ?
                    """,
                    (now, actor, alert_id),
                )
            elif new_status == "resolved":
                conn.execute(
                    """
                    UPDATE alerts
                    SET status = 'resolved', resolved_at = ?, resolved_by = ?, resolution_notes = ?
                    WHERE id = ?
                    """,
                    (now, actor, notes, alert_id),
                )
            else:
                raise ValueError(f"Unsupported alert status transition: {new_status}")

            conn.execute(
                """
                INSERT INTO alert_status_history (alert_id, old_status, new_status, changed_by, notes, changed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (alert_id, old_status, new_status, actor, notes, now),
            )
            updated = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            return self._deserialize_alert(dict(updated)) if updated else None

    def get_alert_history_log(self, alert_id: int) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM alert_status_history WHERE alert_id = ? ORDER BY changed_at DESC, id DESC",
                (alert_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _deserialize_alert(row: dict[str, Any]) -> dict[str, Any]:
        raw_tr = row.get("triggering_readings")
        if isinstance(raw_tr, str):
            try:
                row["triggering_readings"] = json.loads(raw_tr)
            except json.JSONDecodeError:
                row["triggering_readings"] = {}
        return row

    # ------------------------------------------------------------------
    # Email Settings (encrypted password stored, never returned in raw API)
    # ------------------------------------------------------------------
    def get_email_settings_row(self) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM email_settings WHERE id = 1").fetchone()
            if not row:
                now = utc_now_iso()
                conn.execute(
                    """
                    INSERT INTO email_settings
                    (id, sender_email, encrypted_app_password, recipient_email, smtp_host, smtp_port, use_starttls, enabled, updated_at)
                    VALUES (1, '', '', '', 'smtp.gmail.com', 587, 1, 0, ?)
                    """,
                    (now,),
                )
                row = conn.execute("SELECT * FROM email_settings WHERE id = 1").fetchone()
            data = dict(row)
            data["use_starttls"] = bool(data["use_starttls"])
            data["enabled"] = bool(data["enabled"])
            return data

    def save_email_settings(
        self,
        sender_email: str,
        recipient_email: str,
        smtp_host: str,
        smtp_port: int,
        use_starttls: bool,
        enabled: bool,
        encrypted_app_password: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.connection() as conn:
            if encrypted_app_password is not None:
                conn.execute(
                    """
                    UPDATE email_settings
                    SET sender_email = ?,
                        encrypted_app_password = ?,
                        recipient_email = ?,
                        smtp_host = ?,
                        smtp_port = ?,
                        use_starttls = ?,
                        enabled = ?,
                        updated_at = ?
                    WHERE id = 1
                    """,
                    (
                        sender_email,
                        encrypted_app_password,
                        recipient_email,
                        smtp_host,
                        int(smtp_port),
                        1 if use_starttls else 0,
                        1 if enabled else 0,
                        now,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE email_settings
                    SET sender_email = ?,
                        recipient_email = ?,
                        smtp_host = ?,
                        smtp_port = ?,
                        use_starttls = ?,
                        enabled = ?,
                        updated_at = ?
                    WHERE id = 1
                    """,
                    (
                        sender_email,
                        recipient_email,
                        smtp_host,
                        int(smtp_port),
                        1 if use_starttls else 0,
                        1 if enabled else 0,
                        now,
                    ),
                )
        return self.get_email_settings_row()

    def set_email_enabled(self, enabled: bool) -> dict[str, Any]:
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                "UPDATE email_settings SET enabled = ?, updated_at = ? WHERE id = 1",
                (1 if enabled else 0, now),
            )
        return self.get_email_settings_row()

    def record_email_test_result(self, status: str, message: str) -> None:
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE email_settings
                SET last_test_status = ?, last_test_message = ?, last_test_at = ?, updated_at = ?
                WHERE id = 1
                """,
                (status, message, now, now),
            )

    # ------------------------------------------------------------------
    # System Settings
    # ------------------------------------------------------------------
    def get_system_settings(self) -> dict[str, str]:
        with self.connection() as conn:
            rows = conn.execute("SELECT key, value FROM system_settings").fetchall()
            return {r["key"]: r["value"] for r in rows}

    def update_system_settings(self, updates: dict[str, Any]) -> dict[str, str]:
        now = utc_now_iso()
        with self.connection() as conn:
            for key, value in updates.items():
                str_val = str(value).lower() if isinstance(value, bool) else str(value)
                conn.execute(
                    """
                    INSERT INTO system_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (key, str_val, now),
                )
        return self.get_system_settings()

    # ------------------------------------------------------------------
    # Model Metadata
    # ------------------------------------------------------------------
    def save_model_metadata(
        self,
        model_version: str,
        trained_at: str,
        dataset_path: str,
        metrics: dict[str, Any],
        baseline_stats: dict[str, Any],
    ) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE model_metadata SET is_active = 0")
            conn.execute(
                """
                INSERT INTO model_metadata
                (model_version, trained_at, dataset_path, metrics_json, baseline_stats_json, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    model_version,
                    trained_at,
                    dataset_path,
                    json.dumps(metrics),
                    json.dumps(baseline_stats),
                ),
            )

    def get_active_model_metadata(self) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM model_metadata WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            data["metrics"] = json.loads(data.pop("metrics_json"))
            data["baseline_stats"] = json.loads(data.pop("baseline_stats_json"))
            return data
