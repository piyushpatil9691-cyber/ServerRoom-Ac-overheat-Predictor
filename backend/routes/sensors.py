"""Sensor ingestion, history, quality, and drift endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend.dependencies import get_db, get_monitoring_service, require_operator_auth
from backend.schemas import SensorReadingIn
from backend.services.monitoring_service import MonitoringService
from database.db import DatabaseManager

router = APIRouter(prefix="/api/v1/sensors", tags=["Sensors"])


@router.get("/latest")
def get_latest_sensors(
    unit_id: str | None = Query(default=None),
    db: DatabaseManager = Depends(get_db),
) -> list[dict[str, Any]]:
    return db.get_latest_sensor_readings(unit_id=unit_id)


@router.get("/history")
def get_sensor_history(
    unit_id: str | None = Query(default=None),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    db: DatabaseManager = Depends(get_db),
) -> list[dict[str, Any]]:
    return db.get_sensor_history(
        unit_id=unit_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
def ingest_sensor_reading(
    payload: SensorReadingIn,
    db: DatabaseManager = Depends(get_db),
    mon_svc: MonitoringService = Depends(get_monitoring_service),
) -> dict[str, Any]:
    if not db.get_ac_unit(payload.unit_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown AC unit '{payload.unit_id}'.",
        )
    return mon_svc.process_reading(payload.model_dump())


@router.post("/simulate-tick")
def trigger_simulation_tick(
    request: Request,
    db: DatabaseManager = Depends(get_db),
    mon_svc: MonitoringService = Depends(get_monitoring_service),
    _actor: str = Depends(require_operator_auth),
) -> dict[str, Any]:
    simulator = request.app.state.simulator
    units = db.list_ac_units()
    results: list[dict[str, Any]] = []
    for unit in units:
        reading = simulator.generate_reading(
            unit_id=unit["unit_id"],
            operating_mode=unit.get("operating_mode", "normal"),
        )
        results.append(mon_svc.process_reading(reading))
    return {"processed": len(results), "results": results}


@router.get("/drift")
def get_sensor_drift(
    unit_id: str | None = Query(default=None),
    window: int = Query(default=20, ge=5, le=200),
    db: DatabaseManager = Depends(get_db),
    mon_svc: MonitoringService = Depends(get_monitoring_service),
) -> dict[str, Any]:
    if unit_id:
        if not db.get_ac_unit(unit_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"AC unit '{unit_id}' not found.")
        return mon_svc.get_unit_drift_report(unit_id=unit_id, window_size=window)

    units = db.list_ac_units()
    return {
        "units": [mon_svc.get_unit_drift_report(unit_id=u["unit_id"], window_size=window) for u in units]
    }


@router.get("/quality")
def get_data_quality_summary(
    unit_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=10, le=1000),
    db: DatabaseManager = Depends(get_db),
) -> dict[str, Any]:
    readings = db.get_sensor_history(unit_id=unit_id, limit=limit)
    total = len(readings)
    missing_rows = sum(1 for r in readings if r.get("is_missing_any"))
    out_of_range_rows = sum(1 for r in readings if r.get("quality_status") == "out_of_range")
    drift_rows = sum(1 for r in readings if r.get("quality_status") == "drift_warning")
    recent_warnings = [r for r in readings if r.get("quality_status") != "ok"][:20]
    return {
        "sample_size": total,
        "missing_readings_count": missing_rows,
        "out_of_range_count": out_of_range_rows,
        "drift_warning_count": drift_rows,
        "recent_warnings": recent_warnings,
    }
