#!/usr/bin/env python3
# The exposure guard (infra/k8s/cluster-guards.yaml) without a cluster: which requests the policy
# matches, what its CEL decides for each kind of object, that its binding denies cluster-wide and
# fails closed, and that the bootstrap applies and proves it before anything else runs. CI has no
# CEL engine, so the expressions are evaluated here by a translation that accepts only the CEL
# subset they use and refuses anything else. Every property also fails on a deliberately broken
# copy. The bootstrap's live proof is exercised against a fake API in
# test_bootstrap_buildspec_runtime.py; check_cluster_guards.py validates the schema.
import copy
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GUARD = [d for d in yaml.safe_load_all((ROOT / "infra/k8s/cluster-guards.yaml").read_text()) if d]
BOOTSTRAP = (ROOT / "infra/terraform/deploy/bootstrap-buildspec.yml.tftpl").read_text()
GROUPS = {"services": "", "persistentvolumeclaims": "", "ingresses": "networking.k8s.io"}
TOKENS = re.compile(r"\s+|'[^']*'|\d+|==|!=|&&|\|\||!|\(|\)|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


class Obj(dict):
    """An object as CEL sees it: fields by attribute; a missing one is an error, as in CEL."""

    def __getattr__(self, name):
        if name not in self:
            raise AttributeError(name)
        value = self[name]
        return Obj(value) if isinstance(value, dict) else value


def cel(expression, request, obj):
    """Evaluates the CEL subset the policy uses; anything outside it raises instead of guessing."""
    if "".join(TOKENS.findall(expression)) != expression:
        raise ValueError("CEL beyond the evaluated subset: " + expression)
    python = re.sub(r"has\(([\w.]+)\.(\w+)\)", r"has(\1, '\2')", expression)
    python = python.replace("&&", " and ").replace("||", " or ").replace("size(", "len(")
    python = re.sub(r"!(?!=)", " not ", python)
    return eval(python, {"__builtins__": {}}, {  # noqa: S307 - the input is the repo's own policy, tokenized above
        "request": Obj(request), "object": Obj(obj), "has": lambda o, f: f in o, "len": len})


def matched(policy, resource, operation):
    return any(GROUPS[resource] in r["apiGroups"] and "v1" in r["apiVersions"] and resource in r["resources"]
               and operation in r["operations"] for r in policy["spec"]["matchConstraints"]["resourceRules"])


def admitted(docs, resource, operation, obj):
    """The decision for one request: unmatched, or every validation true. An evaluation error denies
    (failurePolicy Fail), as does any validation that is false."""
    policy = docs[0]
    if not matched(policy, resource, operation):
        return True
    request = {"resource": {"group": GROUPS[resource], "version": "v1", "resource": resource}, "operation": operation}
    try:
        return all(cel(v["expression"], request, obj) for v in policy["spec"]["validations"])
    except AttributeError:
        return policy["spec"].get("failurePolicy") != "Fail"


def service(**spec):
    return {"spec": {"type": "ClusterIP", "ports": [{"port": 80}], **spec}}


# (resource, operation, object) -> admitted?
CASES = {
    "ClusterIP Service": (("services", "CREATE", service()), True),
    "headless ClusterIP Service (Argo CD's repo-server and Redis)": (("services", "CREATE", service(clusterIP="None")), True),
    "ClusterIP Service with an empty externalIPs list": (("services", "CREATE", service(externalIPs=[])), True),
    "ClusterIP Service with externalIPs": (("services", "CREATE", service(externalIPs=["192.0.2.10"])), False),
    "ClusterIP Service updated to add externalIPs": (("services", "UPDATE", service(externalIPs=["192.0.2.10"])), False),
    "LoadBalancer Service": (("services", "CREATE", service(type="LoadBalancer")), False),
    "Service updated to LoadBalancer": (("services", "UPDATE", service(type="LoadBalancer")), False),
    "NodePort Service": (("services", "CREATE", service(type="NodePort")), False),
    "ExternalName Service": (("services", "CREATE", service(type="ExternalName", externalName="example.com")), False),
    "Ingress": (("ingresses", "CREATE", {"spec": {"rules": [{"host": "example.com"}]}}), False),
    "Ingress update": (("ingresses", "UPDATE", {"spec": {"rules": [{"host": "example.com"}]}}), False),
    "PersistentVolumeClaim": (("persistentvolumeclaims", "CREATE", {"spec": {"resources": {"requests": {"storage": "1Gi"}}}}), False),
    "Service deletion (DESTROY and the deploy build can still clean up)": (("services", "DELETE", service(type="LoadBalancer")), True),
}


def properties(docs):
    policy, binding = (docs + [{}, {}])[:2]
    decisions = {name: admitted(docs, *request) == expected for name, (request, expected) in CASES.items()}
    return {
        "a ValidatingAdmissionPolicy and its binding, nothing else": [d.get("kind") for d in docs]
            == ["ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding"],
        "fails closed (failurePolicy Fail)": policy.get("spec", {}).get("failurePolicy") == "Fail",
        # Nothing narrows the policy below its resource rules: no selector, exclusion, match condition,
        # variable or parameter (the live proof runs in finrisk only, so it could not see one).
        "policy matches by resource rules alone, cluster-wide": set(policy.get("spec", {})) == {"failurePolicy", "matchConstraints", "validations"}
            and set(policy["spec"]["matchConstraints"]) == {"resourceRules"}
            and all(set(r) == {"apiGroups", "apiVersions", "operations", "resources"} for r in policy["spec"]["matchConstraints"]["resourceRules"])
            and all(set(v) == {"expression", "message"} for v in policy["spec"]["validations"]),
        "binding denies (not warn or audit), cluster-wide, for this policy": binding.get("spec") == {
            "policyName": policy.get("metadata", {}).get("name"), "validationActions": ["Deny"]},
        **{f"{'admits' if CASES[name][1] else 'denies'}: {name}": ok for name, ok in decisions.items()},
    }


def broken(change):
    docs = copy.deepcopy(GUARD)
    change(docs)
    return docs


def services_rule(docs):
    return docs[0]["spec"]["matchConstraints"]["resourceRules"][0]


CONTROLS = {
    "the externalIPs clause dropped": (
        lambda d: d[0]["spec"]["validations"][1].update(expression="request.resource.resource != 'services' || object.spec.type == 'ClusterIP'"),
        "denies: ClusterIP Service with externalIPs"),
    "NodePort allowed": (
        lambda d: d[0]["spec"]["validations"][1].update(expression=d[0]["spec"]["validations"][1]["expression"].replace(
            "object.spec.type == 'ClusterIP'", "(object.spec.type == 'ClusterIP' || object.spec.type == 'NodePort')")),
        "denies: NodePort Service"),
    "the Ingress and PVC validation dropped": (lambda d: d[0]["spec"]["validations"].pop(0), "denies: Ingress"),
    "PVCs not matched": (lambda d: d[0]["spec"]["matchConstraints"]["resourceRules"].pop(2), "denies: PersistentVolumeClaim"),
    "Service updates not matched": (lambda d: services_rule(d).update(operations=["CREATE"]), "denies: Service updated to LoadBalancer"),
    "Ingress updates not matched": (lambda d: d[0]["spec"]["matchConstraints"]["resourceRules"][1].update(operations=["CREATE"]),
                                    "denies: Ingress update"),
    "Service deletion matched": (lambda d: services_rule(d)["operations"].append("DELETE"),
                                 "admits: Service deletion (DESTROY and the deploy build can still clean up)"),
    "failurePolicy Ignore": (lambda d: d[0]["spec"].update(failurePolicy="Ignore"), "fails closed (failurePolicy Fail)"),
    "a Warn binding": (lambda d: d[1]["spec"].update(validationActions=["Warn"]), "binding denies (not warn or audit), cluster-wide, for this policy"),
    "a binding limited to some namespaces": (
        lambda d: d[1]["spec"].update(matchResources={"namespaceSelector": {"matchLabels": {"guarded": "yes"}}}),
        "binding denies (not warn or audit), cluster-wide, for this policy"),
    "a policy limited to some namespaces": (
        lambda d: d[0]["spec"]["matchConstraints"].update(namespaceSelector={"matchLabels": {"guarded": "yes"}}),
        "policy matches by resource rules alone, cluster-wide"),
    "a policy limited to some objects": (lambda d: d[0]["spec"]["matchConstraints"].update(objectSelector={"matchLabels": {"x": "y"}}),
                                         "policy matches by resource rules alone, cluster-wide"),
    "Services excluded": (lambda d: d[0]["spec"]["matchConstraints"].update(excludeResourceRules=[services_rule(d)]),
                          "policy matches by resource rules alone, cluster-wide"),
    "a match condition that never holds": (lambda d: d[0]["spec"].update(matchConditions=[{"name": "never", "expression": "false"}]),
                                           "policy matches by resource rules alone, cluster-wide"),
    "a parameter kind": (lambda d: d[0]["spec"].update(paramKind={"apiVersion": "v1", "kind": "ConfigMap"}),
                         "policy matches by resource rules alone, cluster-wide"),
    "variables": (lambda d: d[0]["spec"].update(variables=[{"name": "t", "expression": "object.spec.type"}]),
                  "policy matches by resource rules alone, cluster-wide"),
    "a resource rule limited by name": (lambda d: services_rule(d).update(resourceNames=["finrisk-guard-probe"]),
                                        "policy matches by resource rules alone, cluster-wide"),
}


def index(text):
    return BOOTSTRAP.find(text) if text in BOOTSTRAP else len(BOOTSTRAP) + 1


found = properties(GUARD)
checks = {**found}
for name, (change, prop) in CONTROLS.items():
    checks[f"negative control: {name} fails '{prop}'"] = found[prop] and not properties(broken(change))[prop]
try:
    cel("object.spec.ports.exists(p, p.nodePort > 0)", {}, {})
    checks["the evaluator refuses CEL beyond its subset"] = False
except ValueError:
    checks["the evaluator refuses CEL beyond its subset"] = True
# Applied after the namespaces are labelled, proven before anything is installed in them.
checks["bootstrap applies the guard after the namespaces, proves it, then installs Argo CD"] = \
    index('label namespace "$ns" --overwrite') < index("apply cluster-guards.yaml") \
    < index("wait_for 30 guarded") < index('"$H" upgrade --install argocd')
checks["bootstrap's five live dry runs: LoadBalancer, externalIPs, Ingress and PVC denied, ClusterIP admitted"] = all(s in BOOTSTRAP for s in (
    """[ "$(denied_by Service "$lb")" = policy ] && [ "$(denied_by Ingress "$ingress")" = policy ]""",
    '[ "$(denied_by PersistentVolumeClaim "$pvc")" = policy ] && external="$(denied_by Service "$ips")"',
    """&& probe Service "$clusterip" >/dev/null""", """lb='{"type":"LoadBalancer","ports":[{"port":80}]}'""",
    """ips='{"type":"ClusterIP","externalIPs":["192.0.2.10"],"ports":[{"port":80}]}'""",
    """clusterip='{"type":"ClusterIP","ports":[{"port":80}]}'""",
    """ingress='{"defaultBackend":{"service":{"name":"finrisk-guard-probe","port":{"number":80}}}}'""",
    """pvc='{"accessModes":["ReadWriteOnce"],"resources":{"requests":{"storage":"1Gi"}}}'""",
    'if [ "$1" = Ingress ]; then api=networking.k8s.io/v1; fi', "create --dry-run=server",
    "ValidatingAdmissionPolicy '{0}' with binding '{0}' denied request".format(GUARD[0]["metadata"]["name"])))

failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}: {k}")
if failed:
    raise SystemExit("Cluster guard acceptance failed: " + ", ".join(failed))
