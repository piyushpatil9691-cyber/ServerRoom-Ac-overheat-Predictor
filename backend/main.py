"""FastAPI backend entrypoint and independent background alert-monitoring loop."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from alerts.alert_service import AlertEngine
from alerts.email_service import EmailService
from backend.routes import alerts, email_config, predictions, sensors, system, units
from backend.services.monitoring_service import MonitoringService
from backend.services.prediction_service import PredictionService
from config import get_settings
from database.db import DatabaseManager
from ml.predict import ACFailurePredictor
from ml.train_model import train_and_save_model
from simulator.sensor_generator import SensorSimulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _background_monitoring_loop(app: FastAPI) -> None:
    """Runs independently of Streamlit browser sessions to process readings and evaluate alerts."""
    db: DatabaseManager = app.state.db
    mon_svc: MonitoringService = app.state.monitoring_service
    pred_svc: PredictionService = app.state.prediction_service
    alert_engine: AlertEngine = app.state.alert_engine
    simulator: SensorSimulator = app.state.simulator
    settings = get_settings()

    last_sim_tick = 0.0
    while True:
        try:
            sys_settings = db.get_system_settings()
            in_process_sim = settings.in_process_simulator or (
                os.environ.get("IN_PROCESS_SIMULATOR", "false").lower() == "true"
            )
            sim_enabled = str(sys_settings.get("simulator_enabled", "true")).lower() == "true"
            sim_interval = max(1, int(float(sys_settings.get("simulator_interval_seconds", "3"))))

            now_mono = time.monotonic()
            if in_process_sim and sim_enabled and (now_mono - last_sim_tick >= sim_interval):
                if pred_svc.predictor.is_loaded():
                    for unit in db.list_ac_units():
                        reading = simulator.generate_reading(
                            unit_id=unit["unit_id"],
                            operating_mode=unit.get("operating_mode", "normal"),
                        )
                        mon_svc.process_reading(reading)
                last_sim_tick = now_mono

            # Also evaluate any unpredicted readings inserted directly into SQLite
            if pred_svc.predictor.is_loaded():
                with db.connection() as conn:
                    unpredicted_rows = conn.execute(
                        """
                        SELECT sr.* FROM sensor_readings sr
                        LEFT JOIN predictions p ON p.reading_id = sr.id
                        WHERE p.id IS NULL
                        ORDER BY sr.id ASC
                        LIMIT 25
                        """
                    ).fetchall()
                for row in unpredicted_rows:
                    reading_dict = db._deserialize_reading(dict(row))
                    pred = pred_svc.predict_and_store(reading_dict, reading_id=reading_dict["id"])
                    alert_engine.evaluate_prediction(
                        unit_id=reading_dict["unit_id"],
                        prediction_id=pred["id"],
                        prediction=pred,
                        reading=reading_dict,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Error in background monitoring loop: %s", exc)

        await asyncio.sleep(settings.alert_poll_interval_seconds)


def create_app(
    db_path: str | None = None,
    model_path: str | None = None,
    metrics_path: str | None = None,
    start_background_loop: bool = True,
) -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        db = DatabaseManager(db_path=db_path)
        db.init_db()

        predictor = ACFailurePredictor(model_path=model_path, metrics_path=metrics_path)
        if not predictor.model_path.exists() and os.environ.get("AUTO_TRAIN_IF_MISSING", "true").lower() == "true":
            logger.info("Trained model missing at %s; generating dataset and training model...", predictor.model_path)
            train_and_save_model(model_path=predictor.model_path, metrics_path=predictor.metrics_path, sync_db=False)
        if predictor.model_path.exists():
            predictor.load()
            report = predictor.get_evaluation_report()
            if report and db.get_active_model_metadata() is None:
                db.save_model_metadata(
                    model_version=report.get("model_version", "rf-ac-predictor-v1.0"),
                    trained_at=report.get("trained_at", ""),
                    dataset_path=report.get("dataset_info", {}).get("dataset_path", ""),
                    metrics=report,
                    baseline_stats=report.get("baseline_stats", {}),
                )
        else:
            logger.warning("Model file not found at %s; prediction endpoints will fail until trained.", predictor.model_path)

        email_svc = EmailService(db)
        alert_engine = AlertEngine(db, email_svc)
        pred_svc = PredictionService(db, predictor)
        mon_svc = MonitoringService(db, pred_svc, alert_engine)
        simulator = SensorSimulator()

        app_instance.state.db = db
        app_instance.state.email_service = email_svc
        app_instance.state.alert_engine = alert_engine
        app_instance.state.prediction_service = pred_svc
        app_instance.state.monitoring_service = mon_svc
        app_instance.state.simulator = simulator

        bg_task: asyncio.Task[None] | None = None
        if start_background_loop:
            bg_task = asyncio.create_task(_background_monitoring_loop(app_instance))

        try:
            yield
        finally:
            if bg_task is not None:
                bg_task.cancel()
                try:
                    await bg_task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(
        title="Server Room AC Overheat Predictor API",
        description=(
            "Predictive maintenance backend for server room CRAC/AC monitoring, "
            "24-hour failure classification, drift/missing-data detection, and alert management."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        sanitized_errors = []
        for err in exc.errors():
            clean_err = dict(err)
            loc_str = ".".join(str(p) for p in clean_err.get("loc", ())).lower()
            if any(s in loc_str for s in ("password", "secret", "token", "key")):
                clean_err["input"] = "[REDACTED]"
            clean_err.pop("url", None)
            sanitized_errors.append(clean_err)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": sanitized_errors},
        )

    app.include_router(system.router)
    app.include_router(units.router)
    app.include_router(sensors.router)
    app.include_router(predictions.router)
    app.include_router(alerts.router)
    app.include_router(email_config.router)

    return app


app = create_app()
