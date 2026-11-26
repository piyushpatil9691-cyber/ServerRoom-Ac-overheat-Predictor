"""Inference module separated from training logic."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from config import get_settings
from ml.features import SENSOR_FEATURES, SENSOR_METADATA, classify_risk_level


class ACFailurePredictor:
    """Loads persisted Joblib pipeline and runs single-reading failure predictions."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        metrics_path: str | Path | None = None,
    ) -> None:
        settings = get_settings()
        self.model_path = Path(model_path) if model_path else settings.resolved_path(settings.model_path)
        self.metrics_path = Path(metrics_path) if metrics_path else settings.resolved_path(settings.metrics_path)
        self._artifact: dict[str, Any] | None = None

    def is_loaded(self) -> bool:
        return self._artifact is not None

    def load(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Trained model not found at {self.model_path}. Run `python -m ml.train_model` first."
            )
        self._artifact = joblib.load(self.model_path)

    def ensure_loaded(self) -> dict[str, Any]:
        if self._artifact is None:
            self.load()
        assert self._artifact is not None
        return self._artifact

    def get_baseline_stats(self) -> dict[str, dict[str, float]]:
        artifact = self.ensure_loaded()
        return artifact.get("baseline_stats", {})

    def get_evaluation_report(self) -> dict[str, Any] | None:
        if self.metrics_path.exists():
            return json.loads(self.metrics_path.read_text(encoding="utf-8"))
        return None

    def predict_reading(
        self,
        reading: dict[str, Any],
        alert_threshold: float = 0.70,
    ) -> dict[str, Any]:
        """Run inference on one sensor reading dictionary and explain main contributors."""
        artifact = self.ensure_loaded()
        pipeline = artifact["pipeline"]
        features = artifact.get("features", SENSOR_FEATURES)
        baseline_stats = artifact.get("baseline_stats", {})

        # Preserve None/NaN as np.nan so pipeline SimpleImputer handles missingness cleanly
        row_values: dict[str, float] = {}
        for feat in features:
            val = reading.get(feat)
            row_values[feat] = float(val) if val is not None and not pd.isna(val) else np.nan

        X = pd.DataFrame([row_values], columns=features)
        prob_fail = float(pipeline.predict_proba(X)[0, 1])
        prob_fail = min(max(prob_fail, 0.0), 1.0)
        predicted_class = 1 if prob_fail >= alert_threshold else 0
        risk_level = classify_risk_level(prob_fail)

        importances = pipeline.named_steps["classifier"].feature_importances_
        contributors = self._explain_contributors(row_values, features, importances, baseline_stats)

        return {
            "unit_id": reading.get("unit_id", "UNKNOWN"),
            "predicted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "failure_probability": round(prob_fail, 4),
            "failure_probability_pct": round(prob_fail * 100.0, 2),
            "predicted_class": predicted_class,
            "predicted_status": "Failure Predicted (<=24h)" if predicted_class == 1 else "Normal Operation",
            "risk_level": risk_level,
            "contributing_factors": contributors,
            "model_version": artifact.get("model_version", "rf-ac-predictor-v1.0"),
        }

    @staticmethod
    def _explain_contributors(
        row_values: dict[str, float],
        features: list[str],
        importances: np.ndarray,
        baseline_stats: dict[str, dict[str, float]],
    ) -> list[dict[str, Any]]:
        """Rank sensor factors combining model feature importance and deviation from healthy baseline."""
        factors: list[dict[str, Any]] = []
        for feat, imp in zip(features, importances):
            val = row_values.get(feat, np.nan)
            stats = baseline_stats.get(feat, {})
            mean_val = stats.get("mean")
            std_val = stats.get("std", 1.0)
            meta = SENSOR_METADATA.get(feat, {})

            if np.isnan(val) or mean_val is None:
                z_score = 0.0
                direction = "missing"
                score = float(imp) * 0.25
            else:
                z_score = (val - mean_val) / max(std_val, 1e-4)
                if feat == "fan_speed":
                    # Low fan speed is the primary failure direction
                    adverse_z = max(0.0, -z_score) + 0.3 * max(0.0, z_score)
                elif feat == "compressor_current":
                    adverse_z = abs(z_score)
                else:
                    adverse_z = max(0.0, z_score) + 0.2 * abs(min(0.0, z_score))
                direction = "elevated" if z_score > 0.75 else ("low" if z_score < -0.75 else "nominal")
                score = float(imp) * (1.0 + adverse_z)

            factors.append(
                {
                    "feature": feat,
                    "label": meta.get("label", feat),
                    "unit": meta.get("unit", ""),
                    "value": None if np.isnan(val) else round(float(val), 2),
                    "baseline_mean": round(float(mean_val), 2) if mean_val is not None else None,
                    "z_score": round(float(z_score), 2),
                    "direction": direction,
                    "model_importance": round(float(imp), 4),
                    "contribution_score": round(float(score), 4),
                }
            )

        factors.sort(key=lambda item: item["contribution_score"], reverse=True)
        return factors
