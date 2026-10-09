#!/usr/bin/env python3
# Delivery and recovery: the deploy workflow, and the deploy buildspec's GitOps discipline (one write,
# the digest; convergence on that digest; re-patch of the previous digest on failure; a failed first
# deploy retained) and its time budget (every wait parsed and bounded, worst path within build_timeout).
# The control flow runs against a fake kubectl in test_deploy_buildspec_runtime.py.
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
WAIT_CONTROLS = {
    "a longer convergence wait": ("wait_for 480 converged", "wait_for 1200 converged"),
    "rollout status without --timeout": ('rollout status deployment/"$APP" --timeout=60s || {', 'rollout status deployment/"$APP" || {'),
    "the smoke exec without timeout": ('timeout 90 "$K" -n "$NS" exec', '"$K" -n "$NS" exec'),
    "the PromQL exec without timeout": ('timeout 240 "$K" -n "$NS" exec', '"$K" -n "$NS" exec'),
    "a kubectl call without the request timeout": ('app_json() { kq -n', 'app_json() { "$K" -n'),
    "a check that polls kubectl by its path": ('state="$(kq -n', 'state="$(/opt/finrisk/bin/kubectl -n'),
    "a second polling loop": ('        failure=""\n        # Every', '        while ! reachable; do sleep 5; done\n        failure=""\n        # Every'),
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
    "a second patch through $K": ('        failure=""\n        # Every', '        "$K" -n "$NS" patch applications.argoproj.io "$APP" '
        "-p '{}' --request-timeout=10s || true\n        failure=\"\"\n        # Every"),
    "the digest patch as a JSON patch": ("--type=merge --field-manager=finrisk-digest", "--type=json --field-manager=finrisk-digest"),
}
CONVERGENCE = [
    '            "sync": f["sync"] == "Synced",',
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
]
ok_block = re.search(r"\n        ok = \{\n(.*?)\n        \}\n", buildspec, re.S)
kubectl_verbs = sorted(set(re.findall(r'(?:\bkq|"\$K")(?: -n "\$NS")? (\w+(?: can-i| status)?)', shell)))
writes = [line for line in shell.splitlines() if re.search(r'\bkq\b|"\$K"|kubectl ', line) and "auth can-i" not in line
          and re.search(r"\b(apply|create|delete|scale|replace|edit|annotate|label|undo|restart|set)\b|--as\b", line)]
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
    "kubectl only reads, asks, patches, waits and execs (no apply, create, delete, scale, undo)":
        kubectl_verbs == ["auth can-i", "exec", "get", "patch", "rollout status", "version"] and not writes,
    # Each check is also shown to matter alone by a FAKE_SKEW scenario in test_deploy_buildspec_runtime.py.
    "convergence needs Synced, the PLAN's commit, the compared and synced digests, Succeeded, an automated sync of the "
    "Application's own source, Healthy, and the Deployment observed running the image with a ready replica":
        ok_block is not None and ok_block[1].splitlines() == CONVERGENCE
        and "        if not pending:\n            verdict = \"converged\"\n" in buildspec,
    # Argo CD v3.5.3's autoSync copies spec.source into its operation; only another source is an override.
    "an operation override is sources, manifests, or a source other than the Application's":
        '        override = [k for k in ("sources", "manifests") if dig(started, "sync", k)]\n'
        '        override += ["source"] if dig(started, "sync", "source") not in (None, spec.get("source")) else []\n' in buildspec,
    "a progress deadline counts only once the Deployment observed its current template":
        'elif "ProgressDeadlineExceeded" in progress and ok["image"] and observed:' in buildspec
        and 'observed = (dig(dep, "status", "observedGeneration") or 0) >= (dig(dep, "metadata", "generation") or 1)' in buildspec,
    "rollout status and readiness verified, then the V1 smoke test in the pod":
        '"$K" -n "$NS" rollout status deployment/"$APP" --timeout=60s' in shell and '"ready": f["ready"] >= 1,' in buildspec
        and 'exec -i deploy/"$APP" -c inference -- python - < /tmp/smoke.py' in shell and 'EXPECTED = "${model_sha256}"' in buildspec,
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
    f"the success path leaves {f'{(BUILD_TIMEOUT * 60 - OVERHEAD - SUCCESS) / 60:.1f}' if SUCCESS else '?'} min for PR 3's load phase":
        SUCCESS is not None and BUDGET is not None and SUCCESS < BUDGET,
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
