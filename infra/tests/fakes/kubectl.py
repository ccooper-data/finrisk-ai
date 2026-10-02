#!/usr/bin/env python3
"""Stateful kubectl stand-in for executing the deploy buildspec in tests.

Models what the rollback logic depends on: a Deployment created with the default of one
replica when the manifest sets none, server-side apply that leaves replicas alone, numbered
revisions, rollout undo, delete, and images that never become ready (FAKE_BAD_IMAGES).
FAKE_FAIL_REVISION_GET=1 makes the revision lookup fail like a transient API error.
"""
import json
import os
import re
import sys

STATE = os.environ["FAKE_STATE"]
state = json.load(open(STATE)) if os.path.exists(STATE) else {"deployment": None, "calls": []}
args = sys.argv[1:]
state["calls"].append(" ".join(args))
dep = state["deployment"]
bad = set(filter(None, os.environ.get("FAKE_BAD_IMAGES", "").split(",")))


def done(code=0, out=""):
    json.dump(state, open(STATE, "w"))
    if out:
        print(out, end="")
    sys.exit(code)


def option(prefix):
    return next(a.split("=", 1)[1] for a in args if a.startswith(prefix))


if args[:2] == ["version", "--client"]:
    done(0, "Client Version: fake\n")
if "serviceaccount" in args:
    done(0)
if "apply" in args:
    if "--dry-run=server" in args:
        done(0)
    image = re.search(r"image: (\S+)", open(args[args.index("-f") + 1]).read()).group(1)
    if dep is None:
        state["deployment"] = {"replicas": 1, "image": image, "revision": 1, "history": {"1": image}}
    elif dep["image"] != image:
        revision = max(map(int, dep["history"])) + 1
        dep["history"] = {r: i for r, i in dep["history"].items() if i != image}
        dep["history"][str(revision)] = image
        dep.update(image=image, revision=revision)
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
    state["deployment"] = None
    done(0)
if "scale" in args:
    dep["replicas"] = int(option("--replicas="))
    done(0)
if "exec" in args:
    sys.stdin.read()
    if dep is None or dep["replicas"] == 0 or dep["image"] in bad:
        done(1)
    done(0, "FINRISK_EVIDENCE smoke=passed\n")
print("fake kubectl: unhandled " + " ".join(args), file=sys.stderr)
done(2)
