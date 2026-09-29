from __future__ import annotations

import hashlib
from pathlib import Path

import joblib
import numpy as np
import pytest
from fastapi.testclient import TestClient

import finrisk.serving as serving


class FakeImputer:
    def transform(self, frame):
        return frame.to_numpy(dtype=float)


class FakeModel:
    def predict_proba(self, values):
        probability = min(max(float(np.mean(values)) / 10.0, 0.0), 1.0)
        return np.array([[1.0 - probability, probability]])


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    artifact = tmp_path / "model.joblib"
    joblib.dump(
        {"model": FakeModel(), "imputer": FakeImputer(), "features": ["a", "b"]},
        artifact,
    )
    monkeypatch.setattr(serving, "MODEL_PATH", artifact)
    monkeypatch.setattr(serving, "_bundle", None)
    return TestClient(serving.app), artifact


def test_liveness_does_not_require_model(client):
    api, _ = client
    response = api.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_binds_model_hash(client):
    api, artifact = client
    response = api.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["model_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert response.json()["feature_count"] == 2


def test_prediction_uses_exact_feature_contract(client):
    api, _ = client
    response = api.post("/v1/risk/predict", json={"features": {"a": 2.0, "b": 4.0}})
    assert response.status_code == 200
    assert response.json()["distress_12m_probability"] == pytest.approx(0.3)


def test_prediction_rejects_missing_feature(client):
    api, _ = client
    response = api.post("/v1/risk/predict", json={"features": {"a": 2.0}})
    assert response.status_code == 422
    assert "missing=['b']" in response.json()["detail"]


def test_prediction_rejects_unknown_feature(client):
    api, _ = client
    response = api.post(
        "/v1/risk/predict", json={"features": {"a": 2.0, "b": 4.0, "unexpected": 1.0}}
    )
    assert response.status_code == 422
    assert "unknown=['unexpected']" in response.json()["detail"]
