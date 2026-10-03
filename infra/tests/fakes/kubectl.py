#!/usr/bin/env python3
"""Stateful kubectl stand-in for executing the deploy buildspec in tests.

Models what the rollback logic depends on: a Deployment created with the default of one
replica when the manifest sets none, server-side apply that leaves replicas alone, numbered
revisions, rollout undo, delete (NotFound unless --ignore-not-found), and images that never
become ready (FAKE_BAD_IMAGES). FAKE_FAIL_REVISION_GET=1 makes the revision lookup fail like a
transient API error; FAKE_FAIL_APPLY=1 does the same to the real apply, before it creates anything.
FAKE_FAIL_DRY_RUN=1 makes the server dry run fail. FAKE_PSA_WARNING=1 makes it print the warning
Pod Security admission returns for a Deployment whose Pod template violates the namespace level
(enforce applies to Pods only, so kubectl still exits 0).

exec runs the piped script with Python, as `python -` in the pod would (without -i the pod gets
no program and exits 0), against a local stand-in for the inference API (src/finrisk/serving.py)
that replaces the Service named in the script's BASE line. As in the cluster, exec needs the
Deployment and container the apply created, and the API answers only on a Service port that
selects the Pods and targets FAKE_LISTEN_PORT, the port the image listens on; any other address
fails to connect. The script gets the standard library only (python -I -S), so it cannot rely on
a test dependency the serving image lacks. The API serves FAKE_MODEL_SHA256, and FAKE_SMOKE breaks
one thing. Requests go through the Service and can reach different pods, so some scenarios change
one answer only:
  wrong-sha          every endpoint reports another model (the image carries the wrong artifact)
  ready-wrong-sha    only /health/ready reports another model
  predict-wrong-sha  only the prediction reports another model
  not-ready          every endpoint answers 503, as serving.py does when the model cannot load
  prob-1.5, prob-neg the probability is above 1 or below 0
  prob-int           the prediction is a class label (an int), not a probability
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

STATE = os.environ["FAKE_STATE"]
state = json.load(open(STATE)) if os.path.exists(STATE) else {"deployment": None, "services": {}, "calls": []}
args = sys.argv[1:]
state["calls"].append(" ".join(args))
dep = state["deployment"]
bad = set(filter(None, os.environ.get("FAKE_BAD_IMAGES", "").split(",")))
PSA_WARNING = ('Warning: would violate PodSecurity "restricted:latest": seccompProfile (pod or container '
               '"inference" must set securityContext.seccompProfile.type to "RuntimeDefault" or "Localhost")')
# Names are arbitrary; the script must send exactly the ones /v1/model lists.
FEATURES = ["debt_to_assets", "current_ratio", "return_on_assets", "log_market_cap"]
OTHER_SHA = "0" * 64
NOT_LOADED = {"detail": "Model artifact not found: /app/model/boosted_tree_model.joblib"}


def done(code=0, out=""):
    json.dump(state, open(STATE, "w"))
    if out:
        print(out, end="")
    sys.exit(code)


def option(prefix):
    return next(a.split("=", 1)[1] for a in args if a.startswith(prefix))


def qualified(obj):
    return "%s.%s" % (obj["metadata"]["name"], obj["metadata"].get("namespace", "default"))


def reaches(service, port, template):
    """Whether this Service port leads to the inference API in the Pods of this template."""
    selector = service["spec"].get("selector") or {}
    target = port.get("targetPort", port["port"])
    named = {p.get("name"): p["containerPort"] for c in template["spec"]["containers"] for p in c.get("ports") or []}
    return bool(selector) and selector.items() <= (template["metadata"].get("labels") or {}).items() \
        and named.get(target, target) == int(os.environ["FAKE_LISTEN_PORT"])


def closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class InferenceApi(BaseHTTPRequestHandler):
    """The response shapes of src/finrisk/serving.py for the endpoints the smoke script calls."""
    scenario = os.environ.get("FAKE_SMOKE", "")

    def log_message(self, *_):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def sha(self, endpoint):
        wrong = self.scenario in ("wrong-sha", endpoint + "-wrong-sha")
        return OTHER_SHA if wrong else os.environ["FAKE_MODEL_SHA256"]

    def do_GET(self):
        if self.path not in ("/health/ready", "/v1/model"):
            return self.reply(404, {"detail": "Not Found"})
        if self.scenario == "not-ready":
            return self.reply(503, NOT_LOADED)
        if self.path == "/health/ready":
            return self.reply(200, {"status": "ready", "model_sha256": self.sha("ready"),
                                    "feature_count": len(FEATURES)})
        self.reply(200, {"model_family": "hist_gradient_boosting", "model_sha256": self.sha("model"),
                         "features": FEATURES})

    def do_POST(self):
        if self.path != "/v1/risk/predict":
            return self.reply(404, {"detail": "Not Found"})
        raw = self.rfile.read(int(self.headers.get("content-length", 0)))
        json_body = self.headers.get("content-type", "").split(";")[0] == "application/json"
        try:
            body = json.loads(raw) if json_body else None
        except ValueError:
            body = None
        # PredictionRequest: only "features", a mapping of name to number or null.
        values = body.get("features") if isinstance(body, dict) and set(body) == {"features"} else None
        numbers = isinstance(values, dict) and all(v is None or isinstance(v, (int, float)) for v in values.values())
        if not numbers:
            return self.reply(422, {"detail": "request does not match PredictionRequest"})
        missing, unknown = sorted(set(FEATURES) - set(values)), sorted(set(values) - set(FEATURES))
        if missing or unknown:
            return self.reply(422, {"detail": f"Feature contract mismatch; missing={missing}, unknown={unknown}"})
        if self.scenario == "not-ready":
            return self.reply(503, NOT_LOADED)
        probability = {"prob-1.5": 1.5, "prob-neg": -0.25, "prob-int": 1}.get(self.scenario, 0.0123)
        self.reply(200, {"distress_12m_probability": probability, "model_sha256": self.sha("predict")})


def smoke(script):
    line = re.compile(r'^BASE = "(.*)"$', re.M)
    match = line.search(script)
    base = urllib.parse.urlsplit(match.group(1) if match else "")
    service = re.fullmatch(r"([a-z0-9-]+\.[a-z0-9-]+)\.svc\.cluster\.local", base.hostname or "")
    # A script without this line, or one that skips the Service, would otherwise bypass the stand-in.
    if base.scheme != "http" or base.path or not service:
        print("fake kubectl: smoke script has no BASE line for a Service", file=sys.stderr)
        done(2)
    # Any address but a Service port that leads to the API fails to connect (here it is refused at once).
    reachable = state["services"].get(service[1], {}).get(str(base.port or 80), False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), InferenceApi)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        url = "http://127.0.0.1:%d" % (server.server_address[1] if reachable else closed_port())
        script = line.sub(lambda _: f'BASE = "{url}"', script, count=1)
        # No proxy may see the request; no_proxy=* also stops urllib using macOS system proxies.
        env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
        env["no_proxy"] = "*"
        result = subprocess.run([sys.executable, "-I", "-S", "-"], input=script, env=env, capture_output=True,
                                text=True, timeout=60)
    finally:
        server.shutdown()
        server.server_close()
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        print(f"command terminated with exit code {result.returncode}", file=sys.stderr)
    done(result.returncode)


if args[:2] == ["version", "--client"]:
    done(0, "Client Version: fake\n")
if "serviceaccount" in args:
    done(0)
if "apply" in args:
    if "--dry-run=server" in args:
        if os.environ.get("FAKE_FAIL_DRY_RUN") == "1":
            print("Error from server (Timeout): the server was unable to return a response in the time allotted",
                  file=sys.stderr)
            done(1)
        if os.environ.get("FAKE_PSA_WARNING") == "1":
            print(PSA_WARNING, file=sys.stderr)
        done(0, "".join(f"{kind}/finrisk-inference serverside-applied (server dry run)\n" for kind in
                        ("deployment.apps", "service", "horizontalpodautoscaler.autoscaling")))
    if os.environ.get("FAKE_FAIL_APPLY") == "1":
        print("error: the server is currently unable to handle the request", file=sys.stderr)
        done(1)
    docs = [d for d in yaml.safe_load_all(open(args[args.index("-f") + 1])) if d]
    deployment = next(d for d in docs if d["kind"] == "Deployment")
    template = deployment["spec"]["template"]
    image = template["spec"]["containers"][0]["image"]
    if dep is None:
        dep = state["deployment"] = {"replicas": 1, "image": image, "revision": 1, "history": {"1": image}}
    elif dep["image"] != image:
        revision = max(map(int, dep["history"])) + 1
        dep["history"] = {r: i for r, i in dep["history"].items() if i != image}
        dep["history"][str(revision)] = image
        dep.update(image=image, revision=revision)
    # Revisions are told apart by image only; the rest of the template is the last one applied.
    dep.update(name=qualified(deployment), containers=[c["name"] for c in template["spec"]["containers"]])
    for service in (d for d in docs if d["kind"] == "Service"):
        state["services"][qualified(service)] = {str(p["port"]): reaches(service, p, template)
                                                 for p in service["spec"]["ports"]}
    done(0)
if "get" in args and "deployment" in args:
    query = args[args.index("-o") + 1]
    if "revision" in query:
        if os.environ.get("FAKE_FAIL_REVISION_GET") == "1":
            print("error: the server is currently unable to handle the request", file=sys.stderr)
            done(1)
        if dep is None:
            done(0 if "--ignore-not-found" in args else 1)
        done(0, str(dep["revision"]))
    if "readyReplicas" in query:
        ready = dep["replicas"] if dep and dep["image"] not in bad else 0
        done(0, str(ready) if ready else "")
if "rollout" in args and "status" in args:
    if dep is None:
        done(1)
    done(0 if dep["replicas"] == 0 or dep["image"] not in bad else 1)
if "rollout" in args and "undo" in args:
    target = option("--to-revision=")
    image = dep["history"][target]
    if image != dep["image"]:
        revision = max(map(int, dep["history"])) + 1
        del dep["history"][target]
        dep["history"][str(revision)] = image
        dep.update(image=image, revision=revision)
    done(0)
if "delete" in args and "deployment" in args:
    if dep is None and "--ignore-not-found" not in args:
        print("Error from server (NotFound): deployments.apps not found", file=sys.stderr)
        done(1)
    state["deployment"] = None
    done(0)
if "scale" in args:
    dep["replicas"] = int(option("--replicas="))
    done(0)
if "exec" in args and "--" in args and args[args.index("--") + 1:] == ["python", "-"]:
    flags = args[:args.index("--")]
    name = next(a for a in flags if a.startswith("deploy/")).split("/", 1)[1]
    if dep is None or dep["name"] != "%s.%s" % (name, flags[flags.index("-n") + 1] if "-n" in flags else "default"):
        print(f'Error from server (NotFound): deployments.apps "{name}" not found', file=sys.stderr)
        done(1)
    if dep["replicas"] == 0 or dep["image"] in bad:
        done(1)
    # Without -c, kubectl picks the first container.
    container = flags[flags.index("-c") + 1] if "-c" in flags else dep["containers"][0]
    if container not in dep["containers"]:
        print(f"Error from server (BadRequest): container {container} is not valid for pod {name}-6d4f8b9c7-x2k9p",
              file=sys.stderr)
        done(1)
    if "-i" not in flags and "--stdin" not in flags:
        done(0)
    smoke(sys.stdin.read())
print("fake kubectl: unhandled " + " ".join(args), file=sys.stderr)
done(2)
