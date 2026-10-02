#!/usr/bin/env python3
"""AWS CLI stand-in for running .github/scripts/run-codebuild.sh and the deploy workflow's
cleanup step in tests.

FAKE_AWS_STATE is a JSON file with:
  polls   build statuses for successive status reads; FAIL fails the read the way the CLI does
          once its own retries are used up. The last entry repeats.
  logs    outcomes (OK or FAIL) of successive get-log-events calls; the last entry repeats.
  events  log messages an OK read returns.
stop-build makes later status reads return IN_PROGRESS once more, then STOPPED. Every call is
appended to "calls"; the file is replaced atomically so a test can read it mid-run.
"""
import json
import os
import sys

STATE = os.environ["FAKE_AWS_STATE"]
state = json.load(open(STATE))
args = sys.argv[1:]
state.setdefault("calls", []).append(" ".join(args))


def done(code=0, out=""):
    tmp = STATE + ".tmp"
    json.dump(state, open(tmp, "w"))
    os.replace(tmp, STATE)
    if out:
        print(out)
    sys.exit(code)


def option(name):
    return args[args.index(name) + 1]


def take(key):
    queue = state[key]
    return queue.pop(0) if len(queue) > 1 else queue[0]


if args[:2] == ["codebuild", "start-build"]:
    done(0, option("--project-name") + ":build-1")
if args[:2] == ["codebuild", "stop-build"]:
    state["stopping"] = 1
    done(0)
if args[:2] == ["codebuild", "batch-get-builds"]:
    query = option("--query")
    fields = {"groupName": "/finrisk/codebuild/test", "streamName": "k8s/build-1"}
    if "buildStatus" in query:
        if "stopping" in state:
            fields["buildStatus"] = "IN_PROGRESS" if state["stopping"] else "STOPPED"
            state["stopping"] = 0
        else:
            fields["buildStatus"] = take("polls")
        if fields["buildStatus"] == "FAIL":
            print("Could not connect to the endpoint URL: \"https://codebuild.us-east-1.amazonaws.com/\"",
                  file=sys.stderr)
            done(255)
    # --output text prints a multiselect list tab-separated, in query order.
    done(0, "\t".join(fields[k] for k in sorted((k for k in fields if k in query), key=query.index)))
if args[:2] == ["logs", "get-log-events"]:
    if take("logs") == "FAIL":
        print("An error occurred (ResourceNotFoundException) when calling the GetLogEvents operation: "
              "The specified log stream does not exist.", file=sys.stderr)
        done(254)
    if "--next-token" in args:
        done(0, json.dumps({"events": [], "nextForwardToken": option("--next-token")}))
    done(0, json.dumps({"events": [{"message": m} for m in state["events"]], "nextForwardToken": "f/1"}))
print(f"fake aws: unexpected call {args}", file=sys.stderr)
done(2)
