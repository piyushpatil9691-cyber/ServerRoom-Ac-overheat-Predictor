"""Alert history, active alerts, acknowledgement, and resolution endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.dependencies import get_db
from backend.schemas import AlertActionIn
from database.db import DatabaseManager

router = APIRouter(prefix="/api/v1/alerts", tags=["Alerts"])


@router.get("")
def list_alerts(
    alert_status: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    unit_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: DatabaseManager = Depends(get_db),
) -> list[dict[str, Any]]:
    return db.list_alerts(status=alert_status, severity=severity, unit_id=unit_id, limit=limit)


@router.get("/active")
def list_active_alerts(
    include_acknowledged: bool = Query(default=True),
    unit_id: str | None = Query(default=None),
    db: DatabaseManager = Depends(get_db),
) -> list[dict[str, Any]]:
    target_status = "open" if include_acknowledged else "active"
    return db.list_alerts(status=target_status, unit_id=unit_id, limit=500)


@router.get("/{alert_id}")
def get_alert_detail(alert_id: int, db: DatabaseManager = Depends(get_db)) -> dict[str, Any]:
    alert = db.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alert {alert_id} not found.")
    alert["history"] = db.get_alert_history_log(alert_id)
    return alert


@router.post("/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: int,
    payload: AlertActionIn | None = None,
    db: DatabaseManager = Depends(get_db),
) -> dict[str, Any]:
    existing = db.get_alert(alert_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alert {alert_id} not found.")
    if existing["status"] == "resolved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot acknowledge an already resolved alert.",
        )
    actor = payload.actor if payload else "operator"
    notes = payload.notes if payload else ""
    updated = db.transition_alert_status(alert_id, "acknowledged", actor=actor, notes=notes)
    assert updated is not None
    return updated


@router.post("/{alert_id}/resolve")
def resolve_alert(
    alert_id: int,
    payload: AlertActionIn | None = None,
    db: DatabaseManager = Depends(get_db),
) -> dict[str, Any]:
    existing = db.get_alert(alert_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alert {alert_id} not found.")
    actor = payload.actor if payload else "operator"
    notes = payload.notes if payload else ""
    updated = db.transition_alert_status(alert_id, "resolved", actor=actor, notes=notes)
    assert updated is not None
    return updated
