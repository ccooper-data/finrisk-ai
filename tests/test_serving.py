from __future__ import annotations

import hashlib
from pathlib import Path

import joblib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

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


def scrape(api) -> str:
    response = api.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=")
    return response.text


def metric(text: str, name: str, **labels: str) -> float:
    # Metrics are process-wide, so tests compare scrapes; an absent family reads as 0.
    return sum(s.value for family in text_string_to_metric_families(text) for s in family.samples
               if s.name == name and labels.items() <= s.labels.items())


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


def test_metrics_served_without_a_model(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(serving, "MODEL_PATH", tmp_path / "missing.joblib")
    monkeypatch.setattr(serving, "_bundle", None)
    api = TestClient(serving.app)
    before = scrape(api)
    assert api.get("/health/ready").status_code == 503
    after = scrape(api)
    count = "http_server_duration_milliseconds_count"
    labels = {"http_target": "/health/ready", "http_status_code": "503"}
    assert metric(after, count, **labels) == metric(before, count, **labels) + 1


def test_metrics_count_a_prediction_and_its_latency(client):
    api, _ = client
    before = scrape(api)
    assert api.post("/v1/risk/predict", json={"features": {"a": 2.0, "b": 4.0}}).status_code == 200
    after = scrape(api)
    for name in ("finrisk_predictions_total", "finrisk_inference_duration_milliseconds_count"):
        assert metric(after, name) == metric(before, name) + 1, name
    errors = "finrisk_prediction_errors_total"
    assert metric(after, errors) == metric(before, errors)


def test_metrics_count_a_failed_prediction(client):
    api, _ = client
    before = scrape(api)
    assert api.post("/v1/risk/predict", json={"features": {"a": 2.0}}).status_code == 422
    after = scrape(api)
    errors = {"name": "finrisk_prediction_errors_total", "error_type": "feature_contract"}
    assert metric(after, **errors) == metric(before, **errors) + 1
    assert metric(after, "finrisk_predictions_total") == metric(before, "finrisk_predictions_total")


def test_metrics_carry_no_request_content(tmp_path: Path, monkeypatch):
    artifact = tmp_path / "model.joblib"
    joblib.dump(
        {"model": FakeModel(), "imputer": FakeImputer(), "features": ["canary_feature"]}, artifact
    )
    monkeypatch.setattr(serving, "MODEL_PATH", artifact)
    monkeypatch.setattr(serving, "_bundle", None)
    api = TestClient(serving.app)
    accepted = {"features": {"canary_feature": -98765.4321}}
    rejected = {"features": {"canary_unknown": -12345.6789}}
    assert api.post("/v1/risk/predict", json=accepted).status_code == 200
    assert api.post("/v1/risk/predict", json=rejected).status_code == 422
    # The Host header, path and query are client-supplied too; none may become a label.
    assert api.get("/canary-path?canary_q=1", headers={"host": "canary-host"}).status_code == 404
    text = scrape(api)
    for leaked in ("canary", "-98765.4321", "-12345.6789"):
        assert leaked not in text, leaked
    # The 404 has no route template beside the matched routes; Prometheus rejects a scrape that
    # declares a family twice (the 0.48b0 exporter wrote one per label-key set).
    families = [line.split()[2] for line in text.splitlines() if line.startswith("# TYPE ")]
    assert len(families) == len(set(families))
