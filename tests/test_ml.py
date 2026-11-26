"""Tests for synthetic dataset generation, Random Forest training, evaluation, and inference."""

from __future__ import annotations

import numpy as np

from ml.features import SENSOR_FEATURES, classify_risk_level
from ml.generate_dataset import TARGET_COLUMN, generate_historical_dataset
from ml.predict import ACFailurePredictor
from ml.train_model import train_and_save_model


def test_dataset_generation_and_schema(tmp_path) -> None:
    ds_path = tmp_path / "hist.csv"
    df = generate_historical_dataset(output_path=ds_path, days=15, seed=123)
    assert ds_path.exists()
    assert len(df) > 1000
    for col in SENSOR_FEATURES:
        assert col in df.columns
    assert TARGET_COLUMN in df.columns
    assert set(df[TARGET_COLUMN].unique()).issubset({0, 1})
    assert df[SENSOR_FEATURES].isna().sum().sum() > 0


def test_training_evaluation_and_missing_value_inference(tmp_path) -> None:
    ds_path = tmp_path / "hist.csv"
    mdl_path = tmp_path / "model.joblib"
    mtr_path = tmp_path / "metrics.json"

    generate_historical_dataset(output_path=ds_path, days=25, seed=42)
    report = train_and_save_model(
        dataset_path=ds_path,
        model_path=mdl_path,
        metrics_path=mtr_path,
        seed=42,
        sync_db=False,
    )

    assert mdl_path.exists()
    assert mtr_path.exists()
    metrics = report["metrics"]
    for key in ("accuracy", "precision", "recall", "f1_score", "confusion_matrix", "feature_importance"):
        assert key in metrics
    assert 0.5 < metrics["accuracy"] <= 1.0
    assert 0.5 < metrics["recall"] <= 1.0
    assert len(metrics["feature_importance"]) == len(SENSOR_FEATURES)

    predictor = ACFailurePredictor(model_path=mdl_path, metrics_path=mtr_path)
    predictor.load()
    assert predictor.is_loaded()

    # Healthy reading with missing humidity and None ac_outlet_temp handled by SimpleImputer
    healthy_partial = {
        "unit_id": "AC-01",
        "room_temp": 21.8,
        "ac_outlet_temp": None,
        "ac_inlet_temp": 23.9,
        "humidity": np.nan,
        "compressor_current": 13.0,
        "fan_speed": 1620.0,
    }
    res_healthy = predictor.predict_reading(healthy_partial)
    assert 0.0 <= res_healthy["failure_probability"] <= 1.0
    assert res_healthy["failure_probability"] < 0.5

    # Severe overheat / degraded reading
    failing_reading = {
        "unit_id": "AC-01",
        "room_temp": 29.8,
        "ac_outlet_temp": 24.5,
        "ac_inlet_temp": 31.2,
        "humidity": 68.0,
        "compressor_current": 21.5,
        "fan_speed": 850.0,
    }
    res_fail = predictor.predict_reading(failing_reading)
    assert res_fail["failure_probability"] >= 0.70
    assert res_fail["predicted_class"] == 1
    assert res_fail["risk_level"] in ("High", "Critical")


def test_risk_classification_boundaries() -> None:
    assert classify_risk_level(0.0) == "Low"
    assert classify_risk_level(0.39) == "Low"
    assert classify_risk_level(0.40) == "Medium"
    assert classify_risk_level(0.69) == "Medium"
    assert classify_risk_level(0.70) == "High"
    assert classify_risk_level(0.89) == "High"
    assert classify_risk_level(0.90) == "Critical"
