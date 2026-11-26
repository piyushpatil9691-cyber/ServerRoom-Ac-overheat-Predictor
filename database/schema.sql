PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ac_units (
    unit_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    rated_capacity_kw REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'operational',
    operating_mode TEXT NOT NULL DEFAULT 'normal',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    room_temp REAL,
    ac_outlet_temp REAL,
    ac_inlet_temp REAL,
    humidity REAL,
    compressor_current REAL,
    fan_speed REAL,
    is_missing_any INTEGER NOT NULL DEFAULT 0,
    missing_fields TEXT NOT NULL DEFAULT '[]',
    quality_status TEXT NOT NULL DEFAULT 'ok',
    quality_notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (unit_id) REFERENCES ac_units(unit_id) ON DELETE CASCADE,
    UNIQUE (unit_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_unit_time
    ON sensor_readings(unit_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_time
    ON sensor_readings(recorded_at DESC);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id TEXT NOT NULL,
    reading_id INTEGER,
    predicted_at TEXT NOT NULL,
    failure_probability REAL NOT NULL,
    predicted_class INTEGER NOT NULL,
    risk_level TEXT NOT NULL,
    contributing_factors TEXT NOT NULL DEFAULT '[]',
    model_version TEXT NOT NULL,
    FOREIGN KEY (unit_id) REFERENCES ac_units(unit_id) ON DELETE CASCADE,
    FOREIGN KEY (reading_id) REFERENCES sensor_readings(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_predictions_unit_time
    ON predictions(unit_id, predicted_at DESC);

CREATE INDEX IF NOT EXISTS idx_predictions_time
    ON predictions(predicted_at DESC);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id TEXT NOT NULL,
    prediction_id INTEGER,
    failure_probability REAL NOT NULL,
    risk_level TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    triggering_readings TEXT NOT NULL,
    created_at TEXT NOT NULL,
    acknowledged_at TEXT,
    acknowledged_by TEXT,
    resolved_at TEXT,
    resolved_by TEXT,
    resolution_notes TEXT,
    email_delivery_status TEXT NOT NULL DEFAULT 'pending',
    email_error TEXT,
    last_notified_at TEXT,
    FOREIGN KEY (unit_id) REFERENCES ac_units(unit_id) ON DELETE CASCADE,
    FOREIGN KEY (prediction_id) REFERENCES predictions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_unit_status
    ON alerts(unit_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_status_time
    ON alerts(status, created_at DESC);

CREATE TABLE IF NOT EXISTS alert_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    changed_at TEXT NOT NULL,
    FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alert_history_alert
    ON alert_status_history(alert_id, changed_at DESC);

CREATE TABLE IF NOT EXISTS email_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sender_email TEXT NOT NULL DEFAULT '',
    encrypted_app_password TEXT NOT NULL DEFAULT '',
    recipient_email TEXT NOT NULL DEFAULT '',
    smtp_host TEXT NOT NULL DEFAULT 'smtp.gmail.com',
    smtp_port INTEGER NOT NULL DEFAULT 587,
    use_starttls INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 0,
    last_test_status TEXT,
    last_test_message TEXT,
    last_test_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT NOT NULL,
    trained_at TEXT NOT NULL,
    dataset_path TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    baseline_stats_json TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);
