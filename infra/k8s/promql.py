# In-pod PromQL evidence, polled up to 180 s; queries with a minimum must reach it. No argument: after the
# smoke test. An argument: the load test, that many seconds after its Job was created (the load interval).
import json
import math
import sys
import time
import urllib.parse
import urllib.request

PROMETHEUS = "http://monitoring-prometheus.monitoring.svc.cluster.local:9090"
NS, APP = 'namespace="finrisk"', "finrisk-inference"
PREDICT = NS + ',http_target="/v1/risk/predict"'
KSM = 'job="kube-state-metrics"'
AVAILABLE = 'kube_deployment_status_replicas_available{%s,%s,deployment="%s"}' % (KSM, NS, APP)
HPA = 'kube_horizontalpodautoscaler_status_%%s_replicas{%s,%s,horizontalpodautoscaler="%s"}' % (KSM, NS, APP)
DEPLOY = [
    ("app_up", 'min(up{%s,service="%s"})' % (NS, APP), 1),
    ("ksm_up", "min(up{%s})" % KSM, 1),
    ("requests", "sum(http_server_duration_milliseconds_count{%s})" % PREDICT, 1),
    ("latency_mean_ms", "sum(http_server_duration_milliseconds_sum{%s}) / sum(http_server_duration_milliseconds_count{%s})"
     % (PREDICT, PREDICT), 0),
    ("predictions", "sum(finrisk_predictions_total{%s})" % NS, 1),
    ("inference_p95_ms", "histogram_quantile(0.95, sum by (le) (finrisk_inference_duration_milliseconds_bucket{%s}))" % NS, None),
    ("replicas_available", AVAILABLE, None),
    ("hpa_current_replicas", HPA % "current", None),
]
LOAD = [
    ("hpa_max_current_replicas", "max(max_over_time(%s[W]))" % (HPA % "current"), 2),
    ("hpa_max_desired_replicas", "max(max_over_time(%s[W]))" % (HPA % "desired"), None),
    ("available_min", "min(min_over_time(%s[W]))" % AVAILABLE, 1),
    ("available_max", "max(max_over_time(%s[W]))" % AVAILABLE, None),
    ("request_rate", 'sum(rate(http_server_duration_milliseconds_count{%s,http_status_code="200"}[1m]))' % PREDICT, 1),
]
QUERIES = LOAD if sys.argv[1:] else DEPLOY
started = time.monotonic() - float(sys.argv[1] if sys.argv[1:] else 0)


def value(query):
    try:
        url = PROMETHEUS + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
        with urllib.request.urlopen(url, timeout=5) as response:
            result = json.load(response)["data"]["result"]
        return float(result[0]["value"][1]) if len(result) == 1 else None
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


deadline = time.monotonic() + 180
while True:
    window = "[%ds]" % (time.monotonic() - started)
    values = {name: value(query.replace("[W]", window)) for name, query, _ in QUERIES}
    missing = [n for n, _, low in QUERIES if low is not None and not (values[n] is not None and math.isfinite(values[n]) and values[n] >= low)]
    if not missing or time.monotonic() >= deadline:
        break
    time.sleep(min(10, max(0, deadline - time.monotonic())))
for name, _, _ in QUERIES:
    print("FINRISK_EVIDENCE promql name=%s value=%s" % (name, "none" if values[name] is None else "%g" % values[name]))
if missing:
    sys.exit("promql failed: " + ", ".join(missing))
