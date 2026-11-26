# Server Room AC Overheat Predictor

A predictive maintenance dashboard and alert system for server room CRAC (Computer Room Air Conditioning) units. It simulates and ingests multi-unit cooling telemetry, checks sensor quality and baseline drift, predicts whether an AC unit is likely to fail within the next **24 hours**, and triggers deduplicated dashboard and **Gmail SMTP** alerts before temperatures get out of hand.

---

## Why This Exists

By the time a basic thermostat alarm fires in a server room, rack intake temperatures are already climbing. This project looks at six correlated cooling signals together so early degradation patterns—like falling supply/return temperature delta, slipping fan RPM, or rising compressor draw—surface hours ahead of a breakdown.

What the system does end-to-end:
- Continuously streams realistic sensor readings for three CRAC units (`AC-01`, `AC-02`, `AC-03`) into SQLite via FastAPI.
- Validates incoming data quality (keeping genuine `0.0` readings like a stopped fan distinct from missing `NULL` readings) and monitors rolling sensor drift.
- Scores every reading with a Scikit-learn `RandomForestClassifier` pipeline (`SimpleImputer` + classifier) trained on a 24-hour lookahead failure target.
- Runs an independent background alert engine in FastAPI so alerts still trigger and persist even when no browser tab is open.
- Lets operators configure Gmail SMTP (`STARTTLS`, App Password encrypted with Fernet) directly through the dashboard UI.

---

## Tech Stack

| Area | Tools Used |
|---|---|
| **Backend** | Python 3.13, FastAPI, Uvicorn, Pydantic |
| **Data & ML** | Pandas, NumPy, Scikit-learn (`Pipeline`, `SimpleImputer`, `RandomForestClassifier`), Joblib |
| **Storage** | SQLite (WAL mode, indexed tables, Docker named volume) |
| **Dashboard** | Streamlit (`@st.fragment` live updates), Plotly, Custom CSS |
| **Alerts & Security** | `cryptography.fernet` symmetric encryption, `smtplib` (Gmail `STARTTLS` on port `587`), `email-validator` |
| **Deployment & Tests** | Docker, Docker Compose, `setup.bat` launcher, `pytest`, `httpx` |

---

## How Everything Connects

```text
+-----------------------+       POST /sensors/ingest      +----------------------------------+
|  Sensor Simulator     | ------------------------------> |  FastAPI Backend (:8000)         |
|  (AC-01, AC-02, AC-03)|                                 |  - Missing data & drift checks   |
+-----------------------+                                 |  - Joblib ML inference           |
                                                          |  - Background alert engine       |
                                                          |  - Gmail SMTP (STARTTLS)         |
                                                          +----------------+-----------------+
                                                                           |
                                                                  SQLite (WAL Volume)
                                                                           |
+-----------------------+        REST API (3s poll)       +----------------v-----------------+
|  Maintenance Inbox    | <------ Gmail SMTP (587) ------ |  Streamlit Dashboard (:8501)     |
|  (App Password Auth)  |                                 |  8 Views + Operator Access Gate  |
+-----------------------+                                 +----------------------------------+
```

1. **Simulator (`simulator/sensor_generator.py`)**: Generates timestamped telemetry across normal operation, transient workload spikes, and gradual equipment faults, posting readings to the backend on a configurable interval (default 3s).
2. **Quality & Drift (`backend/services/data_quality.py`)**: Flags missing values without overwriting them, checks physical bounds, and compares recent rolling readings per unit against the healthy training baseline.
3. **Prediction (`ml/predict.py`)**: Feeds the six sensor readings into the saved Joblib pipeline, returning a 24-hour failure probability, risk tier (`Low`, `Medium`, `High`, `Critical`), and the top contributing sensor factors.
4. **Alert Engine (`alerts/alert_service.py`)**: Creates a single open alert per ongoing incident once failure probability crosses the threshold (default `0.70`), respects a configurable email cooldown (default 15 minutes), and keeps the dashboard alert stored even if SMTP delivery fails.

---

## Project Layout

```text
ServerRoomACPredictor/
├── alerts/                 # Alert rules, deduplication/cooldown engine, Gmail SMTP sender
├── backend/                # FastAPI entrypoint, Pydantic schemas, routes, quality/monitoring services
├── dashboard/              # Streamlit app, API client, Plotly charts, CSS theme, and 8 UI views
├── data/                   # Historical CSV dataset and runtime SQLite database location
├── database/               # SQLite schema (schema.sql) and connection/CRUD helpers (db.py)
├── ml/                     # Dataset generator, model training/evaluation, inference, saved models
├── security/               # Fernet encryption/decryption and credential masking helpers
├── simulator/              # Multi-unit CRAC sensor data generator
├── tests/                  # Automated unit, API, security, and end-to-end workflow tests
├── .streamlit/             # Streamlit theme and sidebar config
├── .env.example            # Environment variable template (copy to .env)
├── .dockerignore           # Excludes caches, .env, and local DBs from Docker builds
├── Dockerfile              # Container image build (pre-trains ML model)
├── docker-compose.yml      # Runs backend, simulator, and dashboard with persistent sqlite_data volume
├── setup.bat               # One-click Windows launcher (keeps only one CMD window open)
├── requirements.txt        # Python dependencies
└── README.md
```

---

## Monitored Sensors

| Sensor | Column | Unit | Healthy Range | Warning / Critical |
|---|---|---|---|---|
| **Room Temperature** | `room_temp` | °C | 18.0 – 25.0 °C | Warn ≥ 26.0 °C / Crit ≥ 28.5 °C |
| **AC Outlet Temperature** | `ac_outlet_temp` | °C | 10.0 – 16.5 °C | Warn ≥ 18.0 °C / Crit ≥ 21.0 °C |
| **AC Inlet Temperature** | `ac_inlet_temp` | °C | 20.0 – 28.0 °C | Warn ≥ 29.0 °C / Crit ≥ 32.0 °C |
| **Relative Humidity** | `humidity` | % RH | 35.0 – 60.0 % | Warn ≥ 65.0 % / Crit ≥ 75.0 % |
| **Compressor Current** | `compressor_current` | A | 9.0 – 17.0 A | Warn ≥ 18.5 A / Crit ≥ 21.0 A |
| **Fan Speed** | `fan_speed` | RPM | 1300 – 1900 RPM | Warn < 1200 RPM / Crit < 1000 RPM |

---

## Dataset, Model Training & Real Evaluation Metrics

### How the Synthetic Dataset Works (`ml/generate_dataset.py`)
- Generates **25,920** 15-minute readings covering 90 days across 3 AC units.
- Models daily server rack heat cycles, short non-failing workload spikes (so the model has to distinguish normal heat bumps from real faults), and three degradation modes: `refrigerant_leak`, `fan_wear`, and `compressor_overload`.
- Labels `failure_within_24h = 1` whenever a simulated failure event falls in the future 24-hour window `(t, t + 24h]`. Labels come strictly from the future failure timeline, not a formula on the current row.
- Randomly drops ~2.5% of sensor values (`3,923` missing entries) so missing-value imputation is part of training and testing.

### Training & Split (`ml/train_model.py`)
- Uses a **chronological 75% / 25% split** (`19,440` training rows / `6,480` test rows) so readings from the same degradation run never leak from the future into training.
- Pipeline: `SimpleImputer(strategy="median")` → `RandomForestClassifier(n_estimators=200, max_depth=12, min_samples_leaf=6, class_weight="balanced_subsample", random_state=42)`.

### Measured Holdout Results (`ml/models/model_evaluation.json`)
- **Failure Prevalence (`failure_within_24h = 1`)**: `8.98%`
- **Accuracy**: `97.48%` (`0.9748`)
- **Precision**: `88.02%` (`0.8802`)
- **Recall**: `83.33%` (`0.8333`)
- **F1-Score**: `85.61%` (`0.8561`)
- **ROC-AUC**: `0.9714` | **PR-AUC**: `0.9099`
- **Confusion Matrix (`n = 6,480`)**: `TN = 5832`, `FP = 66`, `FN = 97`, `TP = 485`

**Why accuracy alone falls short:** With failures making up less than 9% of intervals here (and often under 2% in real server rooms), a dummy model that always predicts "No Failure" still scores ~91% accuracy while missing 100% of real breakdowns. Tracking Recall, Precision, F1-score, PR-AUC, and the Confusion Matrix ensures we catch impending faults early without flooding staff with false alarms.

### Risk Tiers
| Failure Probability | Risk Level | Behavior |
|---|---|---|
| `< 40%` | **Low** | Normal monitoring |
| `40% to < 70%` | **Medium** | Unit status flagged as warning |
| `70% to < 90%` | **High** | Creates alert and dispatches email (default threshold `0.70`) |
| `>= 90%` | **Critical** | Critical alert and email notification |

---

## Quick Start (Windows One-Click Launcher)

Double-click **[setup.bat](setup.bat)** in the project folder.

- Only one CMD window stays open; all services run in the background.
- If `.env` does not exist yet, `setup.bat` creates it from `.env.example` and generates a local Fernet encryption key automatically.
- If Docker is running (or installed), it launches `docker compose up -d --build`, waits for health checks, and opens **http://localhost:8501** in your browser.
- If Docker is unavailable, it falls back to running the backend, simulator, and Streamlit dashboard silently via local Python.
- From the launcher window you can open the dashboard (`O`), inspect logs (`L`), restart (`R`), stop all services (`S`), or close the window while leaving everything running (`Q`).

---

## Setting Up Gmail Alerts

Do **not** enter your regular Gmail password. Use a Google App Password:

1. Enable **2-Step Verification** on the sender Gmail account under Google Account → **Security**.
2. Open **Security → App Passwords** and create a 16-character password.
3. In the dashboard (**http://localhost:8501**), open **Email Notification Settings**.
4. Unlock **Operator Authorization** using `OPERATOR_ACCESS_KEY` from your `.env` file.
5. Fill in your sender Gmail address, 16-character App Password, recipient email, `smtp.gmail.com`, port `587`, and enable **STARTTLS** + **Enable Email Alert Notifications**.
6. Click **Save Configuration** and then **Test Email Connection**.

### How Credentials Are Protected
- App Passwords are encrypted with `Fernet` before writing to SQLite.
- `CREDENTIALS_ENCRYPTION_KEY` lives only in `.env` / environment variables—never inside SQLite or Git.
- Settings, unit mode, and email endpoints require `X-Operator-Key` verified with `hmac.compare_digest` against `OPERATOR_ACCESS_KEY`.
- Saved passwords are masked in the UI and stripped from API responses, validation errors, and logs.

---

## API Overview

Interactive Swagger docs are available at **http://localhost:8000/docs**:

- **System**: `GET /api/v1/system/health`, `GET /api/v1/system/status`, `POST /api/v1/system/auth/verify`, `PUT /api/v1/system/settings`
- **Units**: `GET /api/v1/units`, `GET /api/v1/units/{unit_id}/status`, `PUT /api/v1/units/{unit_id}/mode`
- **Sensors**: `GET /api/v1/sensors/latest`, `GET /api/v1/sensors/history`, `POST /api/v1/sensors/ingest`, `POST /api/v1/sensors/simulate-tick`, `GET /api/v1/sensors/drift`, `GET /api/v1/sensors/quality`
- **Predictions & Model**: `GET /api/v1/predictions/latest`, `GET /api/v1/predictions/history`, `GET /api/v1/model/performance`
- **Alerts**: `GET /api/v1/alerts`, `GET /api/v1/alerts/active`, `POST /api/v1/alerts/{id}/acknowledge`, `POST /api/v1/alerts/{id}/resolve`
- **Email**: `GET /api/v1/email/config`, `PUT /api/v1/email/config`, `PATCH /api/v1/email/toggle`, `POST /api/v1/email/test`

---

## Manual Setup & Operations Runbook

### Local Python Development
```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1 | Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Generate a Fernet key and set CREDENTIALS_ENCRYPTION_KEY + OPERATOR_ACCESS_KEY in .env:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

python -m ml.generate_dataset
python -m ml.train_model
python -m pytest -v

# Run backend, simulator, and dashboard (3 terminals, or set IN_PROCESS_SIMULATOR=true for 2):
uvicorn backend.main:app --host 0.0.0.0 --port 8000
python -m simulator.sensor_generator --api-url http://localhost:8000
streamlit run dashboard/app.py --server.port 8501
```

### Docker Operations
- **Start / rebuild**: `docker compose up -d --build`
- **Stop (keeps SQLite volume intact)**: `docker compose down`
- **Restart**: `docker compose restart`
- **Check container status & health**: `docker compose ps` and `curl -f http://localhost:8000/api/v1/system/health`
- **Inspect logs**: `docker compose logs -f backend` (or `simulator`, `dashboard`)
- **Back up SQLite database**:
  ```bash
  docker compose exec backend python -c "import sqlite3; src=sqlite3.connect('/app/data/ac_predictor.db'); dst=sqlite3.connect('/app/data/backup.db'); src.backup(dst); dst.close(); src.close()"
  docker cp ac-predictor-backend:/app/data/backup.db ./ac_predictor_backup.db
  ```
  Keep a separate secure backup of `.env` (`CREDENTIALS_ENCRYPTION_KEY`); without it, encrypted SMTP passwords in the database backup cannot be decrypted.

### Troubleshooting
- **No live readings appearing**: Check `docker compose logs simulator` and verify **Continuous Sensor Simulator Enabled** is on under **System Settings**.
- **Model errors on startup**: Ensure `ml/models/ac_failure_model.joblib` exists or keep `AUTO_TRAIN_IF_MISSING=true` so the backend trains on first boot.
- **Gmail `535 Authentication Failed`**: Verify 2-Step Verification is enabled and you entered a 16-character App Password (not your regular Gmail password). Dashboard alerts still save to SQLite even if SMTP fails.

---

## Known Limitations

1. **Synthetic Training Data**: Historical sensor trajectories are simulated rather than pulled from real CRAC hardware logs; production use would require retraining on site data.
2. **Drift Detection Scope**: Rolling mean-shift and tail checks compare incoming readings against a static healthy baseline without an external calibrated reference probe, so sustained heat-load shifts or early mechanical wear can look like sensor drift.
3. **Single Operator Key**: Configuration endpoints use a shared `OPERATOR_ACCESS_KEY` header rather than per-user accounts or RBAC.
