#!/usr/bin/env python3
# The inference image serves exactly the pinned model, with the libraries that trained it.
import ast
import json
import re
import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
pin = json.loads((ROOT / "model/served-model.json").read_text())
dockerfile = (ROOT / "Dockerfile").read_text()
dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
constraints = (ROOT / "constraints/serving.txt").read_text()
build = (ROOT / ".github/workflows/build-inference-image.yml").read_text()
# The chart's Deployment, the only deploy artifact. Its template lines are dropped, so the rest loads as
# plain YAML; check_inference_chart.py checks the real render.
manifest = (ROOT / "charts/finrisk-inference/templates/deployment.yaml").read_text()
trainer = ast.parse((ROOT / "src/finrisk/modeling/boosted_tree.py").read_text())
# The training pins, then the libraries behind GET /metrics under their own header.
training_pins, telemetry_header, telemetry_pins = constraints.partition("\n# Telemetry stack")
pinned = dict(re.findall(r"^([a-z0-9-]+)==([0-9.]+)$", training_pins, re.M))
telemetry = {"opentelemetry-api", "opentelemetry-sdk", "opentelemetry-instrumentation-fastapi",
             "opentelemetry-exporter-prometheus", "prometheus-client"}
# One exact version per line (OpenTelemetry contrib ships betas such as 0.66b0): no wildcard or marker.
exact_pin = r"^([a-z0-9-]+)==[0-9]+(?:\.[0-9]+)*(?:b[0-9]+)?$"

# PR container validation: PyYAML reads the bare `on:` key as True.
validate = yaml.safe_load((ROOT / ".github/workflows/container-validate.yml").read_text())
validate_paths = validate[True]["pull_request"]["paths"]
validate_job = validate["jobs"]["container"]
validate_steps = validate_job["steps"]
validate_runs = [s.get("run", "") for s in validate_steps]
model_path = re.search(r"FINRISK_MODEL_PATH=(\S+)", dockerfile).group(1)
# The boot step runs with the pod's memory limit; Kubernetes Mi/Gi and docker m/g are both binary units.
pod_limit = next(c["resources"]["limits"]["memory"] for d in yaml.safe_load_all("\n".join(
                     line for line in manifest.splitlines() if "{{" not in line))
                 if d and d.get("kind") == "Deployment" for c in d["spec"]["template"]["spec"]["containers"]
                 if c["name"] == "inference")
docker_memory = re.sub(r"^(\d+)([KMG])i$", lambda m: m.group(1) + m.group(2).lower(), pod_limit)
copied = [s for l in dockerfile.splitlines() if l.startswith("COPY ") for s in l.split()[1:-1] if not s.startswith("--")]
# Every file the COPY sources bring in; a missing source stays listed, since deleting it changes the image.
copied_files = [p.relative_to(ROOT).as_posix() for s in copied
                for p in ((ROOT / s).rglob("*") if (ROOT / s).is_dir() else [ROOT / s]) if not p.is_dir()]


def step(*needles):
    return next((i for i, run in enumerate(validate_runs) if all(n in run for n in needles)), -1)


def path_filtered(path):
    # GitHub path filters: ** crosses directories, * does not.
    globs = [re.escape(p).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") for p in validate_paths]
    return any(re.fullmatch(g, path) for g in globs)


def docker_runs(i):
    # Each `docker run` in step i as (options, image, arguments). An option missing from `valued`
    # that takes a value is read as the image, so the image check fails closed.
    valued = {"--name", "-p", "--tmpfs", "--cap-drop", "--security-opt", "--memory", "-e", "--entrypoint"}
    found = []
    for line in validate_runs[i].replace("\\\n", " ").splitlines() if i >= 0 else []:
        words = iter(shlex.split(line.split("docker run ", 1)[1]) if "docker run " in line else [])
        options = []
        for w in words:
            if not w.startswith("-"):
                found.append((options, w, list(words)))
                break
            options.append(f"{w} {next(words, '')}" if w in valued else w)
    return found


def enforced(i, timeout=True):
    # The step always runs, in the foreground under the default bash -e (no if, continue-on-error,
    # background or shell), every container it starts is the image the build tagged, each ::error::
    # exits 1, and only the cleanup trap may swallow a failure. timeout bounds a hung probe.
    if i < 0:
        return False
    s, run = validate_steps[i], validate_runs[i]
    return set(s) <= {"name", "run", "timeout-minutes"} and not {"if", "continue-on-error", "defaults"} & set(validate_job) \
        and "defaults" not in validate \
        and (not timeout or 0 < s.get("timeout-minutes", 0) <= 10) \
        and all(image == tag for _, image, _ in docker_runs(i)) \
        and not any(re.search(r"\|\|\s*(true|:)(\s|;|$)|set \+e|set \+o errexit|\bexit 0\b", l)
                    for l in run.splitlines() if not l.startswith("trap ")) \
        and run.count("::error::") == len(re.findall(r'echo "::error::[^\n]*\n\s*exit 1(\n|$)', run))


def bundle_shape(tree):
    # Estimator classes, imputer arguments and saved bundle keys; independent of formatting and keyword order.
    shape = set()
    for n in ast.walk(tree):
        f = ast.unparse(n.func) if isinstance(n, ast.Call) else ""
        if f == "SimpleImputer":
            shape.add((f, tuple(map(ast.unparse, n.args)), frozenset((k.arg, ast.unparse(k.value)) for k in n.keywords)))
        elif f == "HistGradientBoostingClassifier":
            shape.add((f,))
        elif f == "joblib.dump" and n.args and isinstance(n.args[0], ast.Dict):
            shape.add((f, frozenset(map(ast.unparse, n.args[0].keys))))
    return shape


NO_RUN = ([], None, ["no docker run"])
built = step("docker build")
tag = re.search(r'--tag "([^"]+)"', validate_runs[built]).group(1) if built >= 0 else None

boot = step("docker run -d", "/health/live")
boot_options, _, boot_args = (docker_runs(boot) or [NO_RUN])[0]
# The commands, not just their words: cleanup armed first, a curl --max-time poll of /health/live
# that a deadline ends with exit 1, then the exact live body and the not-ready answer, whose
# mismatch is an ::error:: and exit 1 (a warning would let it pass).
boot_probes = [
    r"^trap '[^']*docker logs candidate[^']*docker rm -f candidate[^']*' EXIT\n",
    r'\ndeadline=\$\(\(SECONDS \+ \d+\)\)\nuntil \[ "\$\(curl [^\n]*--max-time \d+ http://127\.0\.0\.1:8000/health/live\)" = "200" \]; do\n',
    r'\n *if \[ "\$running" != "true" \] \|\| \[ "\$SECONDS" -ge "\$deadline" \]; then\n *echo "::error::',
    r"""\njq -e '\. == \{"status": "ok"\}' live\.json\n""",
    r'\ncode="\$\(curl [^\n]*-o ready\.json [^\n]*--max-time \d+ http://127\.0\.0\.1:8000/health/ready\)"\n',
    (rf"""\nif \[ "\$code" != "503" \] \|\| ! jq -e '\.detail == "Model artifact not found: {re.escape(model_path)}"' ready\.json >/dev/null; then\n"""
     r' +echo "::error::[^\n]*\n +exit 1\nfi\n'),
]
# /metrics answers 200 and counts the /health/live probes, which the check requires to come first. It
# is the step's last command, so no enclosing if, loop or heredoc can skip it.
metrics_probe = (
    r"""\ncode="\$\(curl -s -o metrics\.txt -w '%\{http_code\}' --max-time \d+ http://127\.0\.0\.1:8000/metrics\)"\n"""
    r"""if \[ "\$code" != "200" \] \|\| ! grep -q '\^http_server_duration_milliseconds_count\{\[\^\}\]\*http_target="/health/live"' metrics\.txt; then\n"""
    r' +echo "::error::[^\n]*\n +exit 1\nfi\n?\Z'
)

imports = step("pip check")
import_runs = docker_runs(imports)
import_code = next((a[1] for o, _, a in import_runs if {"--read-only", "--tmpfs /tmp", "--entrypoint python"} <= set(o)
                    and len(a) == 2 and a[0] == "-c"), "")
import_tree = ast.parse(import_code)
imported = {n.name for s in import_tree.body for n in s.names} if all(isinstance(s, ast.Import) for s in import_tree.body) else set()

stand_in = step("serving.readiness()")
stand_in_options, _, stand_in_args = (docker_runs(stand_in) or [NO_RUN])[0]
# The heredoc must close on the run's last line; an early PY would hand the assertions to bash.
stand_in_lines = validate_runs[stand_in].splitlines() if stand_in >= 0 else []
heredoc = stand_in_lines[1 + next((n for n, l in enumerate(stand_in_lines) if l.endswith("<<'PY'")), len(stand_in_lines)):]
stand_in_tree = ast.parse("\n".join(heredoc[:-1]) if heredoc[-1:] == ["PY"] and "PY" not in heredoc[:-1] else "")
stand_in_calls = {ast.unparse(n.func) for n in ast.walk(stand_in_tree) if isinstance(n, ast.Call)}
stand_in_asserts = [ast.unparse(n.test) for n in ast.walk(stand_in_tree) if isinstance(n, ast.Assert)]
# Every value each name is assigned in the heredoc, so the /metrics counts trace back to the scrape.
stand_in_assigned = {}
for n in ast.walk(stand_in_tree):
    for t in n.targets if isinstance(n, ast.Assign) else []:
        stand_in_assigned.setdefault(ast.unparse(t), []).append(ast.unparse(n.value))

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
    "telemetry libraries behind /metrics pinned exactly, apart from the training pins": bool(telemetry_header)
        and set(re.findall(exact_pin, telemetry_pins, re.M)) == telemetry
        and not telemetry & set(re.findall(r"^([a-z0-9-]+)", training_pins, re.M)),
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
    "PR CI builds the candidate image unconditionally": enforced(built, timeout=False) and tag is not None,
    "PR CI boots the built image read-only: live 200, ready 503 without a model": 0 <= built < boot and enforced(boot)
        and {"-d", "--name candidate", "-p 127.0.0.1:8000:8000", "--read-only", "--tmpfs /tmp", "--cap-drop ALL",
            "--security-opt no-new-privileges", f"--memory {docker_memory}"} <= set(boot_options)
        and boot_args == [] and all(re.search(p, validate_runs[boot]) for p in boot_probes),
    "PR CI serves /metrics from the read-only image without a model": 0 <= built < boot and enforced(boot)
        and re.search(metrics_probe, validate_runs[boot]) is not None
        and -1 < validate_runs[boot].find("8000/health/live") < validate_runs[boot].find("8000/metrics"),
    "PR CI checks requirements and imports the model's modules inside the image": 0 <= built < imports and enforced(imports)
        and any("--entrypoint python" in o and a == ["-m", "pip", "check"] for o, _, a in import_runs)
        and {"finrisk.serving", "sklearn.ensemble", "sklearn.impute", "scipy", "numpy", "pandas", "joblib"} <= imported,
    "PR CI serves a stand-in model through the image's serving code": 0 <= built < stand_in and enforced(stand_in)
        and {"-i", "--read-only", "--tmpfs /tmp", "--entrypoint python"} <= set(stand_in_options)
        and any(o.startswith("-e FINRISK_MODEL_PATH=/tmp/") for o in stand_in_options) and stand_in_args[:1] == ["-"]
        and {"serving.readiness", "serving.predict"} <= stand_in_calls
        and all(any(n in a for a in stand_in_asserts) for n in ("model_sha256", "distress_12m_probability", "status_code == 422")),
    "PR CI reads the stand-in's predictions, errors and latency back from /metrics": 0 <= built < stand_in and enforced(stand_in)
        and stand_in_assigned.get("scraped") == ["serving.prometheus_metrics(Request({'type': 'http', 'headers': []})).body.decode()"]
        and stand_in_assigned.get("exported") == ["{s.name: s.value for f in text_string_to_metric_families(scraped) for s in f.samples}"]
        and {f"exported.get('{n}') == {v}" for n, v in (("finrisk_predictions_total", 2), ("finrisk_prediction_errors_total", 1),
             ("finrisk_inference_duration_milliseconds_count", 3))} <= set(stand_in_asserts),
    "stand-in model has the estimator types and bundle training dumps": len(bundle_shape(trainer)) == 3
        and bundle_shape(trainer) == bundle_shape(stand_in_tree),
    "PR container validation runs for every file the image copies": {"Dockerfile", ".dockerignore"} <= set(validate_paths)
        and bool(copied_files) and all(path_filtered(f) for f in copied_files),
}

failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Inference image acceptance failed: " + ", ".join(failed))
