"""System health, status, settings, and operator auth endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.dependencies import get_db, get_prediction_service, require_operator_auth
from backend.schemas import SystemSettingsUpdate
from backend.services.prediction_service import PredictionService
from database.db import DatabaseManager, utc_now_iso
from security.credential_encryption import is_encryption_configured

router = APIRouter(prefix="/api/v1/system", tags=["System"])


@router.get("/health")
def health_check(
    db: DatabaseManager = Depends(get_db),
    pred_svc: PredictionService = Depends(get_prediction_service),
) -> dict[str, Any]:
    units = db.list_ac_units()
    return {
        "status": "healthy",
        "database": "connected",
        "units_registered": len(units),
        "model_loaded": pred_svc.predictor.is_loaded(),
        "timestamp": utc_now_iso(),
    }


@router.get("/status")
def system_status(
    db: DatabaseManager = Depends(get_db),
    pred_svc: PredictionService = Depends(get_prediction_service),
) -> dict[str, Any]:
    units = db.list_ac_units()
    latest_readings = db.get_latest_sensor_readings()
    latest_preds = db.get_latest_predictions()
    open_alerts = db.list_alerts(status="open", limit=500)
    active_alerts = [a for a in open_alerts if a["status"] == "active"]
    settings = db.get_system_settings()

    operational_count = sum(1 for u in units if u["status"] == "operational")
    attention_count = sum(1 for u in units if u["status"] in ("warning", "critical"))
    last_reading_at = max((r["recorded_at"] for r in latest_readings), default=None)
    highest_prob = max((p["failure_probability"] for p in latest_preds), default=0.0)

    return {
        "status": "operational" if pred_svc.predictor.is_loaded() else "degraded",
        "timestamp": utc_now_iso(),
        "last_data_update": last_reading_at,
        "summary": {
            "total_units": len(units),
            "operational_units": operational_count,
            "attention_units": attention_count,
            "active_alerts": len(active_alerts),
            "open_alerts": len(open_alerts),
            "highest_failure_probability": round(float(highest_prob), 4),
        },
        "model": {
            "loaded": pred_svc.predictor.is_loaded(),
            "model_path": str(pred_svc.predictor.model_path),
        },
        "security": {
            "encryption_key_configured": is_encryption_configured(),
            "operator_auth_enabled": True,
        },
        "settings": settings,
    }


@router.post("/auth/verify")
def verify_operator_auth(_actor: str = Depends(require_operator_auth)) -> dict[str, Any]:
    return {"authorized": True, "role": _actor}


@router.put("/settings")
def update_system_settings(
    payload: SystemSettingsUpdate,
    db: DatabaseManager = Depends(get_db),
    _actor: str = Depends(require_operator_auth),
) -> dict[str, Any]:
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = db.update_system_settings(updates) if updates else db.get_system_settings()
    return {"status": "updated", "settings": updated}
