"""Shared pytest fixtures for Server Room AC Overheat Predictor."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.main import create_app
from config import reload_settings
from database.db import DatabaseManager
from ml.generate_dataset import generate_historical_dataset
from ml.train_model import train_and_save_model


@pytest.fixture(scope="session")
def test_fernet_key() -> str:
    return Fernet.generate_key().decode("utf-8")


@pytest.fixture(scope="session")
def trained_artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    ml_dir = tmp_path_factory.mktemp("ml_artifacts")
    ds_path = ml_dir / "historical.csv"
    mdl_path = ml_dir / "model.joblib"
    mtr_path = ml_dir / "metrics.json"
    generate_historical_dataset(output_path=ds_path, days=20, seed=42)
    train_and_save_model(
        dataset_path=ds_path,
        model_path=mdl_path,
        metrics_path=mtr_path,
        seed=42,
        sync_db=False,
    )
    return {"dataset": ds_path, "model": mdl_path, "metrics": mtr_path}


@pytest.fixture()
def isolated_env(tmp_path: Path, test_fernet_key: str, trained_artifacts: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test_ac.db"
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", test_fernet_key)
    monkeypatch.setenv("OPERATOR_ACCESS_KEY", "test-operator-secret")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MODEL_PATH", str(trained_artifacts["model"]))
    monkeypatch.setenv("METRICS_PATH", str(trained_artifacts["metrics"]))
    monkeypatch.setenv("IN_PROCESS_SIMULATOR", "false")
    reload_settings()

    db = DatabaseManager(db_path=db_path)
    db.init_db()
    return {
        "db": db,
        "db_path": db_path,
        "model_path": trained_artifacts["model"],
        "metrics_path": trained_artifacts["metrics"],
        "operator_key": "test-operator-secret",
        "fernet_key": test_fernet_key,
    }


@pytest.fixture()
def api_client(isolated_env: dict):
    app = create_app(
        db_path=str(isolated_env["db_path"]),
        model_path=str(isolated_env["model_path"]),
        metrics_path=str(isolated_env["metrics_path"]),
        start_background_loop=False,
    )
    with TestClient(app) as client:
        yield client, isolated_env
