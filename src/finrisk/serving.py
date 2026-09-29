from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from opentelemetry import metrics, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider

MODEL_PATH = Path(os.getenv("FINRISK_MODEL_PATH", "/app/model/boosted_tree_model.joblib"))

trace.set_tracer_provider(TracerProvider())
metrics.set_meter_provider(MeterProvider())
tracer = trace.get_tracer("finrisk.serving")
meter = metrics.get_meter("finrisk.serving")
prediction_counter = meter.create_counter("finrisk.predictions", unit="1")
prediction_error_counter = meter.create_counter("finrisk.prediction_errors", unit="1")
inference_latency = meter.create_histogram("finrisk.inference.duration", unit="ms")


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: dict[str, float | int | None] = Field(
        description="Feature values keyed by the exact training feature names."
    )


class ModelBundle:
    def __init__(self, path: Path):
        payload: dict[str, Any] = joblib.load(path)
        required = {"model", "imputer", "features"}
        missing = required.difference(payload)
        if missing:
            raise ValueError(f"Model artifact missing serving contract fields: {sorted(missing)}")
        self.model = payload["model"]
        self.imputer = payload["imputer"]
        self.features = list(payload["features"])
        self.path = path
        self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    def predict(self, values: dict[str, float | int | None]) -> float:
        unknown = sorted(set(values).difference(self.features))
        missing = sorted(set(self.features).difference(values))
        if unknown or missing:
            raise ValueError(
                f"Feature contract mismatch; missing={missing}, unknown={unknown}"
            )
        frame = pd.DataFrame([[values[name] for name in self.features]], columns=self.features)
        transformed = self.imputer.transform(frame)
        return float(self.model.predict_proba(transformed)[0, 1])


app = FastAPI(
    title="FinRisk-AI Inference API",
    version="1.0.0",
    description="Portfolio inference service for the governed FinRisk boosted-tree artifact.",
)
FastAPIInstrumentor.instrument_app(app)

_bundle: ModelBundle | None = None


def get_bundle() -> ModelBundle:
    global _bundle
    if _bundle is None:
        if not MODEL_PATH.is_file():
            raise RuntimeError(f"Model artifact not found: {MODEL_PATH}")
        _bundle = ModelBundle(MODEL_PATH)
    return _bundle


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def readiness() -> dict[str, Any]:
    try:
        bundle = get_bundle()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "status": "ready",
        "model_sha256": bundle.sha256,
        "feature_count": len(bundle.features),
    }


@app.get("/v1/model")
def model_metadata() -> dict[str, Any]:
    try:
        bundle = get_bundle()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "model_family": "hist_gradient_boosting",
        "model_sha256": bundle.sha256,
        "features": bundle.features,
    }


@app.post("/v1/risk/predict")
def predict(request: PredictionRequest) -> dict[str, Any]:
    started = time.perf_counter()
    with tracer.start_as_current_span("finrisk.predict") as span:
        try:
            bundle = get_bundle()
            probability = bundle.predict(request.features)
            span.set_attribute("finrisk.model_sha256", bundle.sha256)
            prediction_counter.add(1)
        except ValueError as exc:
            prediction_error_counter.add(1, {"error.type": "feature_contract"})
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            prediction_error_counter.add(1, {"error.type": "service_unavailable"})
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            inference_latency.record((time.perf_counter() - started) * 1000.0)
    return {
        "distress_12m_probability": probability,
        "model_sha256": bundle.sha256,
    }
