"""Training pipeline for Server Room AC 24-hour failure prediction model."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from config import get_settings
from database.db import DatabaseManager
from ml.evaluate import evaluate_binary_classifier
from ml.features import SENSOR_FEATURES
from ml.generate_dataset import TARGET_COLUMN, generate_historical_dataset

MODEL_VERSION = "rf-ac-predictor-v1.0"


def _compute_baseline_stats(df_train: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Compute healthy operating baseline statistics from training non-failure rows."""
    healthy = df_train[df_train[TARGET_COLUMN] == 0]
    if healthy.empty:
        healthy = df_train

    stats: dict[str, dict[str, float]] = {}
    for col in SENSOR_FEATURES:
        series = healthy[col].dropna()
        mean_val = float(series.mean())
        std_val = float(series.std(ddof=1)) if len(series) > 1 else 1.0
        stats[col] = {
            "mean": round(mean_val, 4),
            "std": round(max(std_val, 1e-4), 4),
            "median": round(float(series.median()), 4),
            "p05": round(float(series.quantile(0.05)), 4),
            "p95": round(float(series.quantile(0.95)), 4),
            "min": round(float(series.min()), 4),
            "max": round(float(series.max()), 4),
        }
    return stats


def train_and_save_model(
    dataset_path: str | Path | None = None,
    model_path: str | Path | None = None,
    metrics_path: str | Path | None = None,
    seed: int = 42,
    sync_db: bool = True,
) -> dict[str, Any]:
    """Train RandomForest pipeline on chronological split to prevent temporal leakage."""
    settings = get_settings()
    ds_path = Path(dataset_path) if dataset_path else settings.resolved_path(settings.historical_dataset_path)
    mdl_path = Path(model_path) if model_path else settings.resolved_path(settings.model_path)
    mtr_path = Path(metrics_path) if metrics_path else settings.resolved_path(settings.metrics_path)

    if not ds_path.exists():
        generate_historical_dataset(output_path=ds_path, seed=seed)

    df = pd.read_csv(ds_path)
    df["timestamp_dt"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values(["timestamp_dt", "unit_id"]).reset_index(drop=True)

    # Chronological 75/25 split across timestamps to prevent future degradation leakage
    unique_times = df["timestamp_dt"].sort_values().unique()
    split_idx = int(len(unique_times) * 0.75)
    cutoff_ts = unique_times[split_idx]

    train_df = df[df["timestamp_dt"] < cutoff_ts].copy()
    test_df = df[df["timestamp_dt"] >= cutoff_ts].copy()

    X_train = train_df[SENSOR_FEATURES]
    y_train = train_df[TARGET_COLUMN].astype(int).to_numpy()
    X_test = test_df[SENSOR_FEATURES]
    y_test = test_df[TARGET_COLUMN].astype(int).to_numpy()

    pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            (
                "classifier",
                RandomForestClassifier(
                    n_estimators=200,
                    max_depth=12,
                    min_samples_leaf=6,
                    class_weight="balanced_subsample",
                    random_state=seed,
                    n_jobs=-1,
                ),
            ),
        ]
    )

    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]

    rf_estimator = pipeline.named_steps["classifier"]
    eval_metrics = evaluate_binary_classifier(
        y_true=y_test,
        y_pred=y_pred,
        y_prob=y_prob,
        feature_names=SENSOR_FEATURES,
        feature_importances=rf_estimator.feature_importances_,
    )

    baseline_stats = _compute_baseline_stats(train_df)
    trained_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    dataset_info = {
        "dataset_path": str(ds_path),
        "total_rows": int(len(df)),
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "split_method": "Chronological 75/25 split (prevents temporal data leakage)",
        "split_cutoff_timestamp": pd.Timestamp(cutoff_ts).isoformat(),
        "train_positive_rate": round(float(y_train.mean()), 4),
        "test_positive_rate": round(float(y_test.mean()), 4),
        "missing_values_total": int(df[SENSOR_FEATURES].isna().sum().sum()),
        "units": sorted(df["unit_id"].unique().tolist()),
        "features": SENSOR_FEATURES,
        "prediction_horizon_hours": 24,
        "limitations": (
            "Model is trained on physics-informed synthetic historical CRAC degradation data. "
            "Real-world deployment requires fine-tuning on site-specific failure logs."
        ),
    }

    artifact_payload = {
        "pipeline": pipeline,
        "features": SENSOR_FEATURES,
        "model_version": MODEL_VERSION,
        "trained_at": trained_at,
        "baseline_stats": baseline_stats,
        "dataset_info": dataset_info,
    }

    mdl_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact_payload, mdl_path)

    full_report = {
        "model_version": MODEL_VERSION,
        "trained_at": trained_at,
        "metrics": eval_metrics,
        "dataset_info": dataset_info,
        "baseline_stats": baseline_stats,
    }
    mtr_path.parent.mkdir(parents=True, exist_ok=True)
    mtr_path.write_text(json.dumps(full_report, indent=2), encoding="utf-8")

    if sync_db:
        db = DatabaseManager()
        db.init_db()
        db.save_model_metadata(
            model_version=MODEL_VERSION,
            trained_at=trained_at,
            dataset_path=str(ds_path),
            metrics=full_report,
            baseline_stats=baseline_stats,
        )

    return full_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Random Forest AC failure prediction model.")
    parser.add_argument("--dataset", type=str, default=None, help="Historical CSV dataset path.")
    parser.add_argument("--model", type=str, default=None, help="Output joblib model path.")
    parser.add_argument("--metrics", type=str, default=None, help="Output evaluation JSON path.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--no-db", action="store_true", help="Skip syncing metadata to SQLite.")
    args = parser.parse_args()

    report = train_and_save_model(
        dataset_path=args.dataset,
        model_path=args.model,
        metrics_path=args.metrics,
        seed=args.seed,
        sync_db=not args.no_db,
    )
    m = report["metrics"]
    print(f"Model saved ({report['model_version']}) trained at {report['trained_at']}")
    print(
        f"Accuracy={m['accuracy']:.4f} | Precision={m['precision']:.4f} | "
        f"Recall={m['recall']:.4f} | F1={m['f1_score']:.4f} | ROC-AUC={m['roc_auc']}"
    )


if __name__ == "__main__":
    main()
