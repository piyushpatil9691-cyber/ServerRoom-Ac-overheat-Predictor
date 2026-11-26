"""Model Performance page showing real Scikit-learn evaluation metrics and dataset details."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from dashboard.api_client import BackendClient
from dashboard.components.charts import confusion_matrix_chart, feature_importance_chart
from dashboard.components.layout import format_timestamp, render_kpi_strip, render_section_header


def render(client: BackendClient, selected_unit: str, sys_status: dict[str, Any] | None) -> None:
    ok, report = client.get_model_performance()
    if not ok or not report:
        st.error(f"Unable to load model evaluation report: {report}")
        return

    metrics = report.get("metrics", {})
    dataset_info = report.get("dataset_info", {})

    render_kpi_strip(
        [
            {
                "label": "Accuracy (Holdout)",
                "value": f"{metrics.get('accuracy', 0) * 100:.2f}%",
                "sub": f"Model: {report.get('model_version', 'rf-v1')}",
                "tone": "ok",
            },
            {
                "label": "Precision",
                "value": f"{metrics.get('precision', 0) * 100:.2f}%",
                "sub": "Positive predictive value",
                "tone": "ok",
            },
            {
                "label": "Recall (Sensitivity)",
                "value": f"{metrics.get('recall', 0) * 100:.2f}%",
                "sub": "Impending failures caught",
                "tone": "ok" if metrics.get("recall", 0) >= 0.75 else "warn",
            },
            {
                "label": "F1-Score / ROC-AUC",
                "value": f"{metrics.get('f1_score', 0) * 100:.2f}%",
                "sub": f"ROC-AUC: {metrics.get('roc_auc', '--')} | PR-AUC: {metrics.get('pr_auc', '--')}",
                "tone": "ok",
            },
        ]
    )

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        cm = metrics.get("confusion_matrix")
        if cm:
            st.plotly_chart(confusion_matrix_chart(cm), width="stretch", theme=None, config={"displayModeBar": False})
    with c2:
        fi = metrics.get("feature_importance")
        if fi:
            st.plotly_chart(feature_importance_chart(fi), width="stretch", theme=None, config={"displayModeBar": False})

    render_section_header("Why Accuracy Alone Is Insufficient")
    st.info(metrics.get("accuracy_limitation_explanation", ""))

    col_rep, col_ds = st.columns(2, gap="medium")
    with col_rep:
        render_section_header("Classification Report")
        rep_dict = metrics.get("classification_report", {})
        rows = []
        for label_key in ["No Failure (0)", "Failure <=24h (1)", "macro avg", "weighted avg"]:
            entry = rep_dict.get(label_key)
            if isinstance(entry, dict):
                rows.append(
                    {
                        "Class / Aggregate": label_key,
                        "Precision": round(entry.get("precision", 0.0), 4),
                        "Recall": round(entry.get("recall", 0.0), 4),
                        "F1-Score": round(entry.get("f1-score", 0.0), 4),
                        "Support": int(entry.get("support", 0)),
                    }
                )
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    with col_ds:
        render_section_header("Dataset & Training Pipeline Summary")
        ds_summary = [
            {"Property": "Prediction Horizon", "Value": f"{dataset_info.get('prediction_horizon_hours', 24)} hours ahead"},
            {"Property": "Total Historical Rows", "Value": str(dataset_info.get("total_rows", "--"))},
            {"Property": "Train / Test Split", "Value": f"{dataset_info.get('train_rows', '--')} / {dataset_info.get('test_rows', '--')} ({dataset_info.get('split_method', '')})"},
            {"Property": "Train Positive Rate", "Value": f"{dataset_info.get('train_positive_rate', 0) * 100:.2f}%"},
            {"Property": "Test Positive Rate", "Value": f"{dataset_info.get('test_positive_rate', 0) * 100:.2f}%"},
            {"Property": "Imputed Missing Readings", "Value": f"{dataset_info.get('missing_values_total', 0)} (SimpleImputer median)"},
            {"Property": "Trained Timestamp", "Value": format_timestamp(report.get("trained_at"))},
        ]
        st.dataframe(pd.DataFrame(ds_summary), width="stretch", hide_index=True)
        if dataset_info.get("limitations"):
            st.caption(f"Dataset Limitation: {dataset_info['limitations']}")
