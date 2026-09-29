#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
serving = (ROOT.parent / "src" / "finrisk" / "serving.py").read_text()
observability = (ROOT / "terraform" / "observability.tf").read_text()
variables = (ROOT / "terraform" / "variables.tf").read_text()
slos = (ROOT.parent / "docs" / "runtime-slos.md").read_text()

checks = {
    "FastAPI OpenTelemetry instrumentation": "FastAPIInstrumentor.instrument_app(app)" in serving,
    "prediction counter": 'create_counter("finrisk.predictions"' in serving,
    "error counter": 'create_counter("finrisk.prediction_errors"' in serving,
    "latency histogram": 'create_histogram("finrisk.inference.duration"' in serving,
    "model SHA trace attribute": 'finrisk.model_sha256' in serving,
    "observability defaults off": 'variable "enable_observability"' in observability
        and "default     = false" in observability,
    "bounded log retention": "retention_in_days = var.inference_log_retention_days" in observability
        and "default     = 7" in observability,
    "server error alarm": 'metric_name         = "ServerErrors"' in observability,
    "p95 latency alarm": 'extended_statistic  = "p95"' in observability,
    "latency SLO documented": "p95 < 300 ms" in slos,
    "availability SLO documented": "99.9%" in slos,
    "SLO is not uptime claim": "not claims of measured 24/7 production availability" in slos,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Observability acceptance failed: " + ", ".join(failed))
