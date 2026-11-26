"""AC unit information, live status, and simulation mode control endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from backend.dependencies import get_db, get_monitoring_service, require_operator_auth
from backend.schemas import UnitModeUpdate
from backend.services.monitoring_service import MonitoringService
from database.db import DatabaseManager

router = APIRouter(prefix="/api/v1/units", tags=["AC Units"])


@router.get("")
def list_units(db: DatabaseManager = Depends(get_db)) -> list[dict[str, Any]]:
    return db.list_ac_units()


@router.get("/{unit_id}")
def get_unit(unit_id: str, db: DatabaseManager = Depends(get_db)) -> dict[str, Any]:
    unit = db.get_ac_unit(unit_id)
    if not unit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"AC unit '{unit_id}' not found.")
    return unit


@router.get("/{unit_id}/status")
def get_unit_status(
    unit_id: str,
    db: DatabaseManager = Depends(get_db),
    mon_svc: MonitoringService = Depends(get_monitoring_service),
) -> dict[str, Any]:
    unit = db.get_ac_unit(unit_id)
    if not unit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"AC unit '{unit_id}' not found.")
    latest_reading = db.get_latest_sensor_readings(unit_id=unit_id)
    latest_pred = db.get_latest_predictions(unit_id=unit_id)
    open_alert = db.get_open_alert_for_unit(unit_id)
    drift = mon_svc.get_unit_drift_report(unit_id=unit_id)
    return {
        "unit": unit,
        "latest_reading": latest_reading[0] if latest_reading else None,
        "latest_prediction": latest_pred[0] if latest_pred else None,
        "open_alert": open_alert,
        "drift": drift,
    }


@router.put("/{unit_id}/mode")
def set_unit_operating_mode(
    unit_id: str,
    payload: UnitModeUpdate,
    db: DatabaseManager = Depends(get_db),
    _actor: str = Depends(require_operator_auth),
) -> dict[str, Any]:
    updated = db.update_ac_unit_status(unit_id, operating_mode=payload.operating_mode)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"AC unit '{unit_id}' not found.")
    return updated
