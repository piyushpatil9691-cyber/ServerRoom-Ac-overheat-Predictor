"""Evaluation metrics, feature importance, and domain explanations for failure prediction."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

ACCURACY_LIMITATION_EXPLANATION = (
    "In predictive maintenance for server room cooling equipment, failure events within the next "
    "24 hours are relatively uncommon compared to normal operating intervals (typically 10-15% positive "
    "prevalence in this dataset, and often <2% in production). A naive classifier that always predicts "
    "'No Failure' can achieve 85-98% accuracy while missing 100% of impending failures (0% recall), "
    "leading to catastrophic thermal shutdowns. Therefore, Recall (catching real failures before overheat), "
    "Precision (avoiding alert fatigue), F1-score, PR-AUC, and Confusion Matrix analysis are essential "
    "alongside accuracy."
)


def evaluate_binary_classifier(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: np.ndarray,
    feature_names: list[str],
    feature_importances: np.ndarray,
) -> dict[str, Any]:
    """Compute real classification metrics and structured evaluation report."""
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = (int(cm[0, 0]), int(cm[0, 1]), int(cm[1, 0]), int(cm[1, 1]))

    report_dict = classification_report(
        y_true,
        y_pred,
        labels=[0, 1],
        target_names=["No Failure (0)", "Failure <=24h (1)"],
        output_dict=True,
        zero_division=0,
    )
    report_text = classification_report(
        y_true,
        y_pred,
        labels=[0, 1],
        target_names=["No Failure (0)", "Failure <=24h (1)"],
        zero_division=0,
    )

    unique_classes = np.unique(y_true)
    roc_auc = float(roc_auc_score(y_true, y_prob)) if len(unique_classes) > 1 else None
    pr_auc = float(average_precision_score(y_true, y_prob)) if len(unique_classes) > 1 else None

    importances_list = sorted(
        [
            {"feature": name, "importance": round(float(imp), 6)}
            for name, imp in zip(feature_names, feature_importances)
        ],
        key=lambda item: item["importance"],
        reverse=True,
    )

    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1_score": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(roc_auc, 4) if roc_auc is not None else None,
        "pr_auc": round(pr_auc, 4) if pr_auc is not None else None,
        "confusion_matrix": {
            "matrix": [[tn, fp], [fn, tp]],
            "tn": tn,
            "fp": fp,
            "fn": fn,
            "tp": tp,
            "labels": ["No Failure (0)", "Failure <=24h (1)"],
        },
        "classification_report": report_dict,
        "classification_report_text": report_text,
        "feature_importance": importances_list,
        "accuracy_limitation_explanation": ACCURACY_LIMITATION_EXPLANATION,
    }
