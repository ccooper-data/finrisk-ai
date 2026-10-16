# In-pod smoke test through the Service: ready, serving the model whose SHA-256 is argv[1], a valid probability.
import json
import sys
import urllib.request

EXPECTED = sys.argv[1]
BASE = "http://finrisk-inference.finrisk.svc.cluster.local"


def fail(message):
    print("smoke test failed: " + message)
    sys.exit(1)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.load(response)


ready = get("/health/ready")
if ready.get("status") != "ready" or ready.get("model_sha256") != EXPECTED:
    fail("readiness " + json.dumps(ready))
features = get("/v1/model")["features"]
body = json.dumps({"features": dict.fromkeys(features)}).encode()
request = urllib.request.Request(
    BASE + "/v1/risk/predict", data=body, headers={"content-type": "application/json"}, method="POST"
)
with urllib.request.urlopen(request, timeout=10) as response:
    prediction = json.load(response)
probability = prediction.get("distress_12m_probability")
if not isinstance(probability, float) or not 0.0 <= probability <= 1.0:
    fail("prediction " + json.dumps(prediction))
if prediction.get("model_sha256") != EXPECTED:
    fail("prediction model " + json.dumps(prediction))
print("FINRISK_EVIDENCE smoke=passed model_sha256=%s feature_count=%d probability=%.6f"
      % (EXPECTED, len(features), probability))
