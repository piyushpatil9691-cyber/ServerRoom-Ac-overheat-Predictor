"""Failure prediction and model evaluation performance endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.dependencies import get_db, get_prediction_service
from backend.services.prediction_service import PredictionService
from database.db import DatabaseManager

router = APIRouter(prefix="/api/v1", tags=["Predictions & Model"])


@router.get("/predictions/latest")
def get_latest_predictions(
    unit_id: str | None = Query(default=None),
    db: DatabaseManager = Depends(get_db),
) -> list[dict[str, Any]]:
    return db.get_latest_predictions(unit_id=unit_id)


@router.get("/predictions/history")
def get_prediction_history(
    unit_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    db: DatabaseManager = Depends(get_db),
) -> list[dict[str, Any]]:
    return db.get_prediction_history(unit_id=unit_id, limit=limit)


@router.get("/model/performance")
def get_model_performance(
    db: DatabaseManager = Depends(get_db),
    pred_svc: PredictionService = Depends(get_prediction_service),
) -> dict[str, Any]:
    report = pred_svc.predictor.get_evaluation_report()
    if report:
        return report
    meta = db.get_active_model_metadata()
    if meta and meta.get("metrics"):
        return meta["metrics"]
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Model evaluation report not found. Train the model first.",
    )
