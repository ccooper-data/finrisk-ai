#!/usr/bin/env python3
# Delivery and recovery: the deploy workflow, and the deploy buildspec's GitOps discipline (one write to
# the Application, the digest; convergence on that digest; re-patch of the previous digest on failure; a
# failed first deploy retained), its load test (the only other writes create and delete the load Job, which
# is deleted on every outcome; a failed load test is never a rollback) and its time budget (every wait
# parsed and bounded, worst path within build_timeout). The control flow runs against a fake kubectl in
# test_deploy_buildspec_runtime.py.
import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
workflow = (ROOT / ".github" / "workflows" / "deploy-inference.yml").read_text()
runner = (ROOT / ".github" / "scripts" / "run-codebuild.sh").read_text()
buildspec = (ROOT / "infra" / "terraform" / "deploy" / "deploy-buildspec.yml.tftpl").read_text()
path_tf = (ROOT / "infra" / "terraform" / "deploy_path.tf").read_text()
SMOKE = (ROOT / "infra" / "k8s" / "smoke.py").read_text()
PROMQL = (ROOT / "infra" / "k8s" / "promql.py").read_text()
MONITORING = yaml.safe_load((ROOT / "infra" / "k8s" / "monitoring-app.yaml").read_text())
TF_LOCALS = dict(re.findall(r'^  (k8s_\w+_(?:namespace|name))\s+= "([^"]+)"$', path_tf, re.M))
steps = yaml.safe_load(workflow)["jobs"]["deploy"]["steps"]
names = [s.get("name", "") for s in steps]
BUILD_TIMEOUT = int(re.search(r'resource "aws_codebuild_project" "k8s_deploy" \{.*?build_timeout\s+= (\d+)', path_tf, re.S)[1])
OVERHEAD = 4 * 60  # provisioning in the VPC, update-kubeconfig, and the work between waits


# --- The deploy buildspec as bash runs it ---------------------------------------------------------
def shell_lines(template):
    """The build command: heredoc bodies (the Python scripts, data to the shell) dropped, comment lines
    dropped, continuation lines joined."""
    script = yaml.safe_load(template)["phases"]["build"]["commands"][0].replace("$${", "${")
    script = re.sub(r"<<'PY'\n.*?\nPY\n", "<<'PY'\n", script, flags=re.S)
    return [line for line in script.replace("\\\n", " ").splitlines() if line.strip() and not line.lstrip().startswith("#")]


def functions(lines):
    """name -> body lines of each shell function (one-line, or closed by a `}` line at column 0), and the
    lines outside them."""
    defs, main, i = {}, [], 0
    while i < len(lines):
        m = re.match(r"(\w+)\(\) \{(.*)$", lines[i])
        if m and m[2].rstrip().endswith("}"):
            defs[m[1]] = [m[2].rstrip()[:-1]]
        elif m:
            end = lines.index("}", i)
            defs[m[1]], i = lines[i + 1:end], end
        else:
            main.append(lines[i])
        i += 1
    return defs, main


# A word at command position: line start, after ; & | ( { ! or $(, or after a shell keyword.
CMD = r"(?:^|[;&|({!]|\$\(|\b(?:if|elif|then|else|do|until|while)\s)\s*"
WAIT_FOR = ['  local deadline=$(( $(date +%s) + $1 ))', '  shift', '  until "$@"; do',
            '    [ "$(date +%s)" -lt "$deadline" ] || return 1', '    sleep 5', '  done']
# Direct kubectl calls (not through kq) that are bounded or local: the client version, rollout status
# with its --timeout, and an exec under coreutils timeout (which is not at command position).
DIRECT = re.compile(r'"\$K" (?:version --client$|-n "\$NS" rollout status deployment/"\$APP" --timeout=\d+s\b)')


def deploy_budget(template):
    """Seconds the deploy can spend waiting at worst, or None when a wait has no recognised bound.
    Every API call is bounded: kq's request timeout, rollout status --timeout, timeout N around exec, and
    a wait_for's literal bound plus one poll and one check. Functions count where they are called (a
    wait_for check by its kq calls); exclusive branches (if/elif/else) count their worst branch."""
    lines = shell_lines(template)
    script, (defs, main) = "\n".join(lines), functions(lines)
    kq = re.fullmatch(r' "\$K" --request-timeout=(\d+)s "\$@"; ', (defs.get("kq") or [""])[0])
    curl = re.findall(r"curl -fsSL --retry \d+ --retry-connrefused --retry-max-time (\d+) --max-time (\d+) ", script)
    if not kq or defs.get("wait_for") != WAIT_FOR or len(curl) != 1 or script.count("curl ") != 1 \
            or len(re.findall(r"\b(?:sleep|until)\b", script)) != 2 or re.search(r"\b(?:while|for)\b|--watch\b|\s-w\b", script):
        return None
    if len(re.findall(r"\bwait_for\b", script)) - 1 != len(re.findall(CMD + r"wait_for \d+ \w+\b", script, re.M)):
        return None  # a wait_for whose bound is not a literal
    request = int(kq[1])

    def calls(name, seen):
        """API calls one run of a wait check makes (all through kq), or None."""
        if name in seen or name not in defs:
            return None
        body = "\n".join(defs[name])
        if re.search(CMD + r'(?:"?\$\{?K\b|\S*kubectl\b)', body, re.M) or re.search(CMD + r"wait_for\b", body, re.M):
            return None
        return len(re.findall(CMD + r"kq\b", body, re.M))

    def cost(line, seen):
        """Seconds one line can take, or None."""
        total, bounded = 0, 0
        for n, check in re.findall(CMD + r"wait_for (\d+) (\w+)\b", line):
            n_calls = calls(check, seen)
            if n_calls is None:
                return None
            total += int(n) + 5 + request * n_calls
        for direct in re.findall(CMD + r'((?:"\$K"|\S*kubectl) .*)$', line):
            if not DIRECT.match(direct):
                return None  # an unbounded API call
        for n in re.findall(r" rollout status \S+ --timeout=(\d+)s\b", line):
            total, bounded = total + int(n), bounded + 1
        for n in re.findall(CMD + r"timeout (\d+) ", line):
            total, bounded = total + int(n), bounded + 1
        if len(re.findall(r"--timeout\b|\btimeout \d", line)) != bounded or ("rollout status" in line) != bool(
                re.search(r"rollout status \S+ --timeout=\d+s", line)):
            return None  # a bound on something not modelled here
        if "exec " in line and not re.search(CMD + r'timeout \d+ "\$K" ', line):
            return None  # exec has no request timeout of its own
        if re.search(CMD + r"kq\b[^|;&]* delete\b", line) and " --wait=false" not in line:
            return None  # delete waits for the object to go, which the request timeout does not bound
        total += request * len(re.findall(CMD + r"kq\b", line))
        total += sum(int(a) + int(b) for a, b in re.findall(r"--retry-max-time (\d+) --max-time (\d+) ", line))
        for name in set(defs) - {"kq", "wait_for"}:
            for _ in re.findall(CMD + re.escape(name) + r"\b", line):
                inner = body_cost(defs[name], (*seen, name)) if name not in seen else None
                if inner is None:
                    return None
                total += inner
        return total

    def body_cost(body, seen):
        """Lines in sequence; an if/elif/else block counts its conditions and its worst branch."""
        stack = [[0]]  # per open block: the branch costs so far (the first entry collects conditions)
        conditions = [0]
        for line in body:
            stripped = line.strip()
            head = re.match(r"(if|elif) (.*); then$", stripped)
            if head:
                c = cost(head[2], seen)
                if c is None:
                    return None
                if head[1] == "if":
                    stack.append([0])
                    conditions.append(c)
                else:
                    stack[-1].append(0)
                    conditions[-1] += c
                continue
            if stripped == "else":
                stack[-1].append(0)
                continue
            if stripped == "fi":
                branches, c = stack.pop(), conditions.pop()
                stack[-1][-1] += c + max(branches)
                continue
            c = cost(line, seen)
            if c is None:
                return None
            stack[-1][-1] += c
        return stack[0][0] if len(stack) == 1 else None

    return body_cost(main, ())


def changed(old, new):
    return buildspec.replace(old, new, 1) if old in buildspec else ""


def budget_fails(template):
    try:
        budget = deploy_budget(template) if template else None
    except (ValueError, IndexError, yaml.YAMLError):
        budget = None
    return budget is None or budget + OVERHEAD > BUILD_TIMEOUT * 60


BUDGET = deploy_budget(buildspec)
SUCCESS = deploy_budget(re.sub(r"\n        else\n.*?\n          exit 1\n        fi\n$", "\n        fi\n", buildspec, flags=re.S))
FAILURE_PATH = re.sub(r"\n        if deploy_and_verify; then\n.*?\n        else\n", "\n        if deploy_and_verify; then\n          :\n        else\n",
                      buildspec, count=1, flags=re.S)
FAILURE = deploy_budget(FAILURE_PATH)
WAIT_CONTROLS = {
    "a longer convergence wait": ("wait_for 480 converged", "wait_for 1200 converged"),
    "rollout status without --timeout": ('rollout status deployment/"$APP" --timeout=60s || {', 'rollout status deployment/"$APP" || {'),
    "the smoke exec without timeout": ('timeout 90 "$K" -n "$NS" exec', '"$K" -n "$NS" exec'),
    "the PromQL exec without timeout": ('if ! timeout 240 "$K" -n "$NS" exec', 'if ! "$K" -n "$NS" exec'),
    "the load PromQL exec without timeout": ('timeout 240 "$K" -n "$NS" exec -i deploy/"$APP" -c inference -- python - $((',
                                             '"$K" -n "$NS" exec -i deploy/"$APP" -c inference -- python - $(('),
    "a longer wait for the HPA": ("wait_for 300 scaled_up", "wait_for 900 scaled_up"),
    "a longer wait for the Job to go": ("wait_for 60 gone", "wait_for 600 gone"),
    "a Job delete that waits for the Job to go": (" --ignore-not-found --wait=false && ", " --ignore-not-found && "),
    "a kubectl call without the request timeout": ('app_json() { kq -n', 'app_json() { "$K" -n'),
    "a check that polls kubectl by its path": ('state="$(kq -n', 'state="$(/opt/finrisk/bin/kubectl -n'),
    "a second polling loop": ('        failure="" late=""\n        # Every',
                              '        while ! reachable; do sleep 5; done\n        failure="" late=""\n        # Every'),
    "a download without --max-time": (" --max-time 40 ", " "),
    "a wait_for whose bound is a variable": ("wait_for 300 converged", 'wait_for "$${ROLLBACK_WAIT:-300}" converged'),
}

# --- The GitOps revision check between the two builds (no AWS call: the bootstrap's evidence line) ---
SHA = "0123456789abcdef0123456789abcdef01234567"
gitops_step = next((s for s in steps if s.get("name") == "Check the GitOps revision is this commit"), {})


def revision_check(evidence):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "deployment.txt"
        path.write_text(evidence)
        run_env = dict(os.environ, EVIDENCE_FILE=str(path), GITHUB_SHA=SHA, BOOTSTRAP_PROJECT="finrisk-ai-portfolio-k8s-bootstrap")
        result = subprocess.run(["bash", "-e", "-c", gitops_step.get("run", "exit 99")], env=run_env, capture_output=True,
                                text=True, timeout=30)
        return result.returncode, path.read_text()


def gitops_line(sha):
    return (f"finrisk-ai-portfolio-k8s-bootstrap: gitops app=finrisk/finrisk-inference project=finrisk target_revision={sha} "
            f"image_repository=780976819607.dkr.ecr.us-east-1.amazonaws.com/finrisk-ai-inference conditions=ComparisonError\n")


REVISION_CASES = {
    "the same commit": (gitops_line(SHA), 0),
    "another commit": (gitops_line("f" * 40), 1),
    "no gitops line": ("finrisk-ai-portfolio-k8s-bootstrap: bootstrap=complete namespace=finrisk\n", 1),
    "two gitops lines": (gitops_line(SHA) + gitops_line(SHA), 1),
    "the line from another project": (gitops_line(SHA).replace("k8s-bootstrap:", "k8s-deploy:"), 1),
}
revision_results = {name: revision_check(text) for name, (text, _) in REVISION_CASES.items()}

shell = "\n".join(shell_lines(buildspec))


def only_digest_write(template):
    """The one kubectl write is the image.digest merge patch by field manager finrisk-digest: exactly one
    kubectl line patches (auth can-i only asks), and it is that one."""
    lines = shell_lines(template)
    patches = [l for l in lines if re.search(r"\bpatch\b", l) and re.search(r'\bkq\b|\$\{?K\b|kubectl', l) and "auth can-i" not in l]
    return len(patches) == 1 and "\n".join(lines).count("--type=") == 1 and patches[0].strip().startswith(
        'kq -n "$NS" patch applications.argoproj.io "$APP" --type=merge --field-manager=finrisk-digest ') and patches[0].strip().endswith(
        '-p "{\\"spec\\":{\\"source\\":{\\"helm\\":{\\"parameters\\":[{\\"name\\":\\"image.digest\\",\\"value\\":\\"$1\\",\\"forceString\\":true}]}}}}"')


WRITE_CONTROLS = {
    "a second, JSON patch whose failure is ignored": ("        set_digest() {\n", "        set_digest() {\n          kq -n \"$NS\" patch "
        "applications.argoproj.io \"$APP\" --type=json -p '[{\"op\":\"remove\",\"path\":\"/spec/syncPolicy/automated/selfHeal\"}]' || :\n"),
    "a second patch through $K": ('        failure="" late=""\n        # Every', '        "$K" -n "$NS" patch applications.argoproj.io "$APP" '
        "-p '{}' --request-timeout=10s || true\n        failure=\"\" late=\"\"\n        # Every"),
    "the digest patch as a JSON patch": ("--type=merge --field-manager=finrisk-digest", "--type=json --field-manager=finrisk-digest"),
}
CONVERGENCE = [
    '            "sync": f["sync"] == "Synced" or f["sync"] == "OutOfSync" and bool(oos) and set(oos) <= chart,',
    '            "revision": f["revision"] == REVISION,',
    '            "operation_revision": dig(started, "sync", "revision") in (None, REVISION),',
    '            "compared": f["compared"] == WANT,',
    '            "operation": f["operation"] == "Succeeded",',
    '            "synced": f["synced"] == WANT,',
    '            "synced_revision": f["synced_revision"] == REVISION,',
    '            "automated": f["automated"],',
    '            "override": not override,',
    '            "health": f["health"] == "Healthy",',
    '            "image": image == "%s@%s" % (dig(spec, "source", "helm", "valuesObject", "image", "repository"), WANT),',
    '            "observed": observed,',
    '            "ready": f["ready"] >= 1,',
    '            # Every replica updated and available, none of an earlier template.',
    '            "updated": rs[0] == rs[1] == rs[2] >= (dig(dep, "spec", "replicas") or 1),',
    '            # A missing HPA shows only as OutOfSync (a missing ServiceMonitor fails app_up).',
    '            "hpa": "HorizontalPodAutoscaler" in kinds,',
]
ok_block = re.search(r"\n        ok = \{\n(.*?)\n        \}\n", buildspec, re.S)
# The load test's two writes: the Job from the embedded, sha256-checked file with the image just deployed,
# and its deletion (not waited on; a bounded poll checks it is gone).
LOAD_WRITES = ['sed "s#LOAD_IMAGE#$FINRISK_IMAGE_URI#" /tmp/load-job.yaml | kq -n "$NS" create -f - || { load=load_not_started; return 1; }',
               'kq -n "$NS" delete job finrisk-load --ignore-not-found --wait=false && wait_for 60 gone && deleted=yes || deleted=no']


def kubectl_use(template):
    """The kubectl verbs the build uses, and its lines that write anything other than the digest patch."""
    shell = "\n".join(shell_lines(template))
    verbs = sorted(set(re.findall(r'(?:\bkq|"\$K")(?: -n "\$NS")? (\w+(?: can-i| status)?)', shell)))
    writes = [line.strip() for line in shell.splitlines() if re.search(r'\bkq\b|"\$K"|kubectl ', line) and "auth can-i" not in line
              and re.search(r"\b(apply|create|delete|scale|replace|edit|annotate|label|undo|restart|set|cordon|drain|taint)\b|--as\b", line)]
    return verbs, writes


def only_load_job_writes(template):
    verbs, writes = kubectl_use(template)
    return verbs == ["auth can-i", "create", "delete", "exec", "get", "patch", "rollout status", "version"] and writes == LOAD_WRITES


def job_always_deleted(template):
    """load_test runs once, as a condition (so set -e cannot end the build inside it), then the delete runs
    unconditionally, before any result: on every outcome of the load test."""
    defs, main = functions(shell_lines(template))
    calls = [l for l in main if re.search(CMD + r"load_test\b", l)]
    if any(re.search(CMD + r"load_test\b", "\n".join(body), re.M) for body in defs.values()):
        return False
    try:
        run, delete = main.index("  load_test || :"), main.index("  " + LOAD_WRITES[1])
    except ValueError:
        return False
    indent = [len(l) - len(l.lstrip()) for l in main[run:delete + 1]]
    return calls == ["  load_test || :"] and run < delete < next(i for i, l in enumerate(main) if "result=$load" in l) \
        and set(indent) == {2} and not any(LOAD_WRITES[1] in "\n".join(body) for body in defs.values())


START = '          load="" top=0 start="" scaled=no\n'
LOAD_CONTROLS = {
    "a delete of the Application": (START, START + '          kq -n "$NS" delete applications.argoproj.io "$APP" || :\n'),
    "a scale of the Deployment": (START, START + '          kq -n "$NS" scale deployment "$APP" --replicas=3 || :\n'),
    "the Job with another image": ('s#LOAD_IMAGE#$FINRISK_IMAGE_URI#', 's#LOAD_IMAGE#python:3.12-slim#'),
    "a second object created": (START, START + '          kq -n "$NS" create configmap finrisk-load || :\n'),
}
DELETE = "          " + LOAD_WRITES[1] + "\n"
CLEANUP_CONTROLS = {
    "the delete only after a passing load test": lambda s: s.replace("          load_test || :\n          kq -n", "          load_test && kq -n", 1),
    "the delete inside the load test (skipped by its early returns)": lambda s: s.replace(DELETE, "", 1).replace(
        "          show during\n", "          show during\n" + DELETE, 1) if DELETE in s else "",
    "load_test run where set -e applies": lambda s: s.replace("          load_test || :\n", "          load_test\n", 1),
    "the delete after the result": lambda s: s.replace(DELETE, "", 1).replace(
        '          echo "FINRISK_EVIDENCE result=deployed $ids"\n', '          echo "FINRISK_EVIDENCE result=deployed $ids"\n' + DELETE, 1)
        if DELETE in s else "",
}


def promql_queries(text):
    """The in-pod PromQL script's queries, from its constants (run whole, the script polls Prometheus)."""
    scope = {}
    exec(text[:text.index("\nQUERIES = ")], scope)
    return [query for _, query, _ in scope["DEPLOY"] + scope["LOAD"]]


def ksm_pinned(text):
    """Every kube-state-metrics series it reads (kube_*, the replica counts the gate rests on) is selected by
    kube-state-metrics' own scrape job, so no other target's series of that name can answer for it."""
    series = [s for query in promql_queries(text) for s in re.findall(r"\bkube_\w+\{([^}]*)\}", query)]
    return len(series) == 6 and all('job="kube-state-metrics"' in s.split(",") for s in series)


KSM_CONTROLS = {
    "available replicas by namespace and name only": ("% (KSM, NS, APP)\nHPA = ", "% (NS, NS, APP)\nHPA = "),
    "HPA replicas by namespace and name only": ("_replicas{%s,%s,horizontalpodautoscaler=\"%s\"}' % (KSM, NS, APP)",
                                                 "_replicas{%s,%s,horizontalpodautoscaler=\"%s\"}' % (NS, NS, APP)"),
}
checks = {
    "manual bounded deployment": "workflow_dispatch:" in workflow,
    "OIDC permission": "id-token: write" in workflow,
    "short-lived AWS credentials": "aws-actions/configure-aws-credentials@v5" in workflow,
    "release role, not the Terraform role": "vars.AWS_RELEASE_ROLE_ARN" in workflow and "AWS_DEPLOY_ROLE_ARN" not in workflow,
    "deploys the image built from its own commit": 'tag="sha-${GITHUB_SHA}"' in workflow and "sha-[0-9a-f]{40}" in workflow,
    "no image input to redirect the deploy": "inputs:" not in workflow,
    "digest resolution": "imageDigest" in workflow,
    "digest deployment": "@$digest" in workflow and 'FINRISK_IMAGE_URI=${{ steps.image.outputs.uri }}' in workflow,
    "cluster add-ons bootstrapped before deploy": workflow.index("Bootstrap cluster add-ons") < workflow.index("Deploy digest-pinned image"),
    # The image is this run's commit; Argo CD's chart is the PLAN's (frozen main makes them one commit).
    "the deploy starts only when the bootstrap pinned Argo CD to this run's commit": 0 <= names.index("Bootstrap cluster add-ons")
        < names.index("Check the GitOps revision is this commit") < names.index("Deploy digest-pinned image")
        and set(gitops_step) == {"name", "run"} and all(
            revision_results[name][0] == code for name, (_, code) in REVISION_CASES.items())
        and revision_results["the same commit"][1].endswith(f"gitops_revision_check={SHA}\n"),
    "build failure fails the job": 'if [ "$status" != "SUCCEEDED" ]' in runner,
    # GitOps deploy discipline
    "previous digest read before the patch": buildspec.index('PREV_DIGEST="$(app_json | python3 /tmp/app.py validate')
        < buildspec.index('set_digest "$DIGEST"'),
    "the only write is a merge patch of the image.digest parameter, by field manager finrisk-digest": only_digest_write(buildspec),
    **{f"negative control: {name} is caught": bool(changed(old, new)) and not only_digest_write(changed(old, new))
       for name, (old, new) in WRITE_CONTROLS.items()},
    "kubectl reads, asks, patches the digest, waits and execs; its only other writes create and delete the load Job":
        only_load_job_writes(buildspec),
    **{f"negative control: {name} is caught": bool(changed(old, new)) and not only_load_job_writes(changed(old, new))
       for name, (old, new) in LOAD_CONTROLS.items()},
    "the load Job is deleted on every outcome of the load test, before any result line": job_always_deleted(buildspec),
    **{f"negative control: {name} is caught": mutate(buildspec) not in ("", buildspec) and not job_always_deleted(mutate(buildspec))
       for name, mutate in CLEANUP_CONTROLS.items()},
    # The release passed its smoke test before the load test, so a failed load test is not a rollback.
    "a failed load test fails the build without a re-patch, under its own result": re.search(
        r'\n          if \[ -n "\$load" \]; then\n            echo "FINRISK_EVIDENCE result=\$load \$ids"\n            exit 1\n          fi\n'
        r'          echo "FINRISK_EVIDENCE result=deployed \$ids"\n        else\n', buildspec) is not None
        and set(re.findall(r"\bload=(\w+)", buildspec)) == {"load_not_started", "hpa_not_scaled", "hpa_evidence_failed", "load_cleanup_failed"}
        and not re.search(r"roll|recover|set_digest", buildspec[buildspec.index("        scaled_up() {"):buildspec.index("        if deploy_and_verify; then")]
                          + buildspec[buildspec.index('          load="" top=0'):buildspec.index("        else\n          echo \"FINRISK_EVIDENCE failure=")]),
    "the PromQL evidence reads kube-state-metrics' replica series from its own scrape job only": ksm_pinned(PROMQL),
    **{f"negative control: {name} is caught": old in PROMQL and not ksm_pinned(PROMQL.replace(old, new, 1))
       for name, (old, new) in KSM_CONTROLS.items()},
    # The embedded in-pod scripts name what Terraform and the monitoring Application name.
    "the in-pod scripts address the release's Service and the monitoring stack's Prometheus by their real names":
        f'BASE = "http://{TF_LOCALS["k8s_app_name"]}.{TF_LOCALS["k8s_app_namespace"]}.svc.cluster.local"\n' in SMOKE
        and f'NS, APP = \'namespace="{TF_LOCALS["k8s_app_namespace"]}"\', "{TF_LOCALS["k8s_app_name"]}"\n' in PROMQL
        and f'PROMETHEUS = "http://{MONITORING["spec"]["source"]["helm"]["valuesObject"]["fullnameOverride"]}-prometheus.'
            f'{MONITORING["spec"]["destination"]["namespace"]}.svc.cluster.local:9090"\n' in PROMQL
        and MONITORING["spec"]["destination"]["namespace"] == TF_LOCALS["k8s_monitoring_namespace"],
    "the load test starts only from 1 replica, and passes only at 2 or more by kubectl and by kube-state-metrics":
        '[[ "$hpa" == 1\\ * ]] || { load=load_not_started; return 1; }' in buildspec
        and '&& [[ "$hpa" == [2-9]\\ * ]]' in buildspec and "wait_for 300 scaled_up && scaled=yes || load=hpa_not_scaled" in buildspec
        and '("hpa_max_current_replicas", "max(max_over_time(%s[W]))" % (HPA % "current"), 2),' in PROMQL
        and '("available_min", "min(min_over_time(%s[W]))" % AVAILABLE, 1),' in PROMQL,
    # Each check is also shown to matter alone by a FAKE_SKEW scenario in test_deploy_buildspec_runtime.py.
    "convergence needs Synced (or OutOfSync on the chart's HPA and ServiceMonitor only), the PLAN's commit, the compared and "
    "synced digests, Succeeded, an automated sync of the Application's own source, Healthy, the Deployment observed running "
    "only the image, every replica updated and available, and the HPA present":
        ok_block is not None and ok_block[1].splitlines() == CONVERGENCE
        and "        if not pending:\n            verdict = \"converged\"\n" in buildspec,
    # Never the Deployment or the Service: drift there could change what serves or the smoke test's path.
    "OutOfSync is tolerated only for the chart's HPA and ServiceMonitor, by group, kind, namespace and name; every template "
    "image counts, init containers included; the poll reads the HPA, and the preflight checks it may":
        '        chart = {"autoscaling/HorizontalPodAutoscaler/${namespace}/${app}", '
        '"monitoring.coreos.com/ServiceMonitor/${namespace}/${app}"}\n' in buildspec
        and '        oos = ["/".join(r.get(k) or "" for k in ("group", "kind", "namespace", "name")) '
            'for r in status.get("resources") or [] if r.get("status") != "Synced"]\n' in buildspec
        and '        image = ",".join(c.get("image") or "none" for k in ("initContainers", "containers") '
            'for c in dig(dep, "spec", "template", "spec", k) or []) or "none"\n' in buildspec
        and 'get "applications.argoproj.io/$APP" "deployment/$APP" "hpa/$APP" --ignore-not-found -o json' in shell
        and '        expect get_deployment yes get "deployment/$APP" -n "$NS"\n'
            '        expect get_hpa yes get "hpa/$APP" -n "$NS"\n' in buildspec,
    # Argo CD v3.5.3's autoSync copies spec.source into its operation; only another source is an override.
    "an operation override is sources, manifests, or a source other than the Application's":
        '        override = [k for k in ("sources", "manifests") if dig(started, "sync", k)]\n'
        '        override += ["source"] if dig(started, "sync", "source") not in (None, spec.get("source")) else []\n' in buildspec,
    "a progress deadline counts only once the Deployment observed its current template":
        'elif "ProgressDeadlineExceeded" in progress and ok["image"] and observed:' in buildspec
        and 'observed = (dig(dep, "status", "observedGeneration") or 0) >= (dig(dep, "metadata", "generation") or 1)' in buildspec,
    "rollout status and readiness verified, then the V1 smoke test in the pod, against the pinned model's SHA-256":
        '"$K" -n "$NS" rollout status deployment/"$APP" --timeout=60s' in shell and '"ready": f["ready"] >= 1,' in buildspec
        and 'exec -i deploy/"$APP" -c inference -- python - "${model_sha256}" < /tmp/smoke.py' in shell
        and "EXPECTED = sys.argv[1]\n" in SMOKE,
    "a non-first failure re-patches the previous digest and waits again":
        'set_digest "$PREV_DIGEST" && wait_for 300 converged "$PREV_DIGEST" && [ -z "$failure" ]' in shell
        and "result=rolled_back" in buildspec and "result=rollback_failed" in buildspec,
    "a failed first deploy is retained (no delete right, no finalizer), and not called a rollback":
        "result=first_deploy_retained" in buildspec and not re.search(
            r"roll|recover", buildspec[buildspec.index('if [ "$PREV_DIGEST" = none ]'):buildspec.index('elif [ "$PREV_DIGEST" = "$DIGEST" ]')], re.I),
    "missing PromQL evidence fails the build without a rollback": re.search(
        r'if ! timeout 240 "\$K" -n "\$NS" exec -i deploy/"\$APP" -c inference -- python - < /tmp/promql\.py; then\n'
        r'\s+echo "FINRISK_EVIDENCE result=observability_failed \$ids"\n\s+exit 1\n', buildspec) is not None
        and buildspec.index("promql.py; then") > buildspec.index("if deploy_and_verify; then")
        and buildspec.index("promql.py; then") < buildspec.index("        else\n          echo \"FINRISK_EVIDENCE failure="),
    "every failure stays failed": buildspec.rstrip().endswith("exit 1\n        fi"),
    f"deploy waits at their bounds, worst path ({f'{BUDGET / 60:.1f} min' if BUDGET else 'one has no recognised bound'}), "
    f"plus {OVERHEAD // 60} min fit build_timeout ({BUILD_TIMEOUT} min)": BUDGET is not None and BUDGET + OVERHEAD <= BUILD_TIMEOUT * 60,
    # The load test runs on the success path only; both paths are parsed.
    f"the success path, load test included, waits {f'{SUCCESS / 60:.1f}' if SUCCESS else '?'} min at its bounds, the failure path "
    f"(re-patch) {f'{FAILURE / 60:.1f}' if FAILURE else '?'} min; the worst of them is the budget":
        None not in (SUCCESS, FAILURE, BUDGET) and max(SUCCESS, FAILURE) == BUDGET and "load_test || :" not in FAILURE_PATH,
    **{f"negative control: {name} is caught": bool(changed(old, new)) and budget_fails(changed(old, new))
       for name, (old, new) in WAIT_CONTROLS.items()},
    "deployment evidence retained": "finrisk-deployment-evidence" in workflow and "FINRISK_EVIDENCE" in runner,
    "deployment serialized with provision/destroy": "group: finrisk-bounded-aws-validation" in workflow
        and "cancel-in-progress: false" in workflow,
    "abandoned builds are stopped": "stop-build" in runner and "trap stop_if_running EXIT" in runner,
    # Behaviour is exercised against a fake aws in test_run_codebuild_runtime.py.
    "a cancel reaches the runner's trap at once": workflow.count("run: exec .github/scripts/run-codebuild.sh") == 2
        and "& wait $!" in runner,
    "cancelled or failed runs stop unfinished builds before releasing the group": "- name: Stop unfinished builds" in workflow
        and "if: failure() || cancelled()" in workflow
        and workflow.index("Stop unfinished builds") < workflow.index("Upload deployment evidence"),
    "success requires the final evidence line": "final evidence line was not found" in runner and "--next-token" in runner,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Delivery/recovery acceptance failed: " + ", ".join(failed))
