#!/usr/bin/env python3
# The inference image serves exactly the pinned model, with the libraries that trained it.
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
pin = json.loads((ROOT / "model/served-model.json").read_text())
dockerfile = (ROOT / "Dockerfile").read_text()
dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
constraints = (ROOT / "constraints/serving.txt").read_text()
build = (ROOT / ".github/workflows/build-inference-image.yml").read_text()
manifest = (ROOT / "infra/k8s/inference.yaml").read_text()
pinned = dict(re.findall(r"^([a-z0-9-]+)==([0-9.]+)$", constraints, re.M))

checks = {
    "pin names run, artifact, size and sha256": set(pin) == {"source_workflow", "model_run_id", "artifact_name", "file", "size_bytes", "sha256"}
        and pin["model_run_id"].isdigit() and pin["artifact_name"].endswith(pin["model_run_id"])
        and isinstance(pin["size_bytes"], int) and re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) is not None,
    "build takes no model input (pin only)": "inputs:" not in build and "model/served-model.json" in build,
    "build verifies source run provenance": all(s in build for s in (".head_branch", ".conclusion", ".event", "source_workflow")),
    "build verifies size and sha256 before docker": "PINNED_SIZE" in build and "PINNED_SHA256" in build
        and build.index("PINNED_SHA256") < build.index("docker build"),
    "build smoke-tests the image before push": build.index("Verify candidate serves the model") < build.index("docker push")
        and "--read-only" in build and "/v1/risk/predict" in build,
    "image tags are never overwritten": "already exists" in build,
    "serving libraries pinned to the training versions": {"scikit-learn", "numpy", "pandas", "scipy", "joblib"} <= set(pinned)
        and "-c /app/constraints/serving.txt" in dockerfile,
    "Python matches training (3.12)": dockerfile.splitlines()[[i for i, l in enumerate(dockerfile.splitlines()) if l.startswith("FROM ")][0]] == "FROM python:3.12-slim",
    "numeric non-root user (runAsNonRoot can verify it)": "USER 10001:10001" in dockerfile
        and "runAsUser: 10001" in manifest and "runAsGroup: 10001" in manifest,
    "only the served model may enter the image": "**/*.joblib" in dockerignore
        and "!model/boosted_tree_model.joblib" in dockerignore
        and dockerignore.index("!model/boosted_tree_model.joblib") > dockerignore.index("**/*.joblib"),
    "constraints name the pinned training run": f"run {pin['model_run_id']}," in constraints,
    "build checks the training run's recorded library versions": "boosted_tree_metrics.json" in build
        and "scikit_learn" in build and "FROM python:" in build,
    "build checks library versions inside the image": "Check library versions inside the image" in build,
    "expired pinned artifact fails with a re-pin instruction": ".expired" in build and "Retrain, show prediction equivalence" in build,
    "model file never committed": (ROOT / "model/.gitignore").read_text().strip() == "*.joblib",
    "writable /tmp with read-only root": "readOnlyRootFilesystem: true" in manifest and "mountPath: /tmp" in manifest,
    "pod gets no Kubernetes API token": "automountServiceAccountToken: false" in manifest,
}

failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Inference image acceptance failed: " + ", ".join(failed))
