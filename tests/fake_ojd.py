#!/usr/bin/env python3
"""Stand-in for OpenJoystickDriver's `ojd virtual feed`, for tests.

Validates frames the way ojd's VirtualFeedFrame decoder does (unknown keys,
unknown names and duplicates exit with code 64) and appends each one to the
file named by FAKE_OJD_LOG.  FAKE_OJD_FAIL makes it exit immediately.
"""
import json
import os
import sys

CONTROLS = {"South", "East", "West", "North", "LeftShoulder", "RightShoulder", "LeftTrigger",
            "RightTrigger", "Back", "Start", "LeftStickClick", "RightStickClick", "Guide", "Capture"}
DPAD = {"DpadUp", "DpadDown", "DpadLeft", "DpadRight"}
AXES = {"LeftStickX", "LeftStickY", "RightStickX", "RightStickY", "LeftTrigger", "RightTrigger"}

if sys.argv[1:3] != ["virtual", "feed"] or sys.argv[3] != "--as":
    sys.exit(2)
if os.environ.get("FAKE_OJD_FAIL"):
    print("error: the OpenJoystickDriver service is not running", file=sys.stderr)
    sys.exit(69)
log = open(os.environ["FAKE_OJD_LOG"], "a")
log.write(json.dumps({"persona": sys.argv[4]}) + "\n")
for line in sys.stdin:
    f = json.loads(line)
    ok = set(f) <= {"buttons", "dpad", "axes", "holdMilliseconds"}
    for key, names in (("buttons", CONTROLS), ("dpad", DPAD)):
        vals = f.get(key, [])
        ok &= len(vals) == len(set(vals)) and set(vals) <= names
    ok &= set(f.get("axes", {})) <= AXES
    if not ok:
        print(f"invalid frame: {line}", file=sys.stderr)
        sys.exit(64)
    log.write(line)
    log.flush()
