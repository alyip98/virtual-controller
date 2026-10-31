import json
import sys

import pytest

from posepad.backends import BackendUnavailable
from posepad.backends.ojd import OJDBackend, frame
from posepad.bindings import ControllerState
from posepad.config import ConfigError, parse_profile

FAKE = [sys.executable, str(__import__("pathlib").Path(__file__).with_name("fake_ojd.py"))]


@pytest.fixture
def fake_ojd(tmp_path, monkeypatch):
    exe = tmp_path / "ojd"
    exe.write_text(f"#!/bin/sh\nexec {FAKE[0]} {FAKE[1]} \"$@\"\n")
    exe.chmod(0o755)
    log = tmp_path / "frames.jsonl"
    monkeypatch.setenv("FAKE_OJD_LOG", str(log))
    return str(exe), log


def test_frame_mapping():
    st = ControllerState(buttons={"A", "LB", "DPAD_UP", "START"})
    st.axes.update(left_x=0.5, left_y=1.0, rt=0.25)
    f = frame(st)
    assert f["buttons"] == ["LeftShoulder", "South", "Start"]
    assert f["dpad"] == ["DpadUp"]
    assert f["axes"] == {"LeftStickX": 0.5, "LeftStickY": -1.0, "RightTrigger": 0.25}  # y flipped
    assert frame(ControllerState()) == {}


def test_streams_valid_frames(fake_ojd):
    exe, log = fake_ojd
    pad = OJDBackend("game-controller-compatible", executable=exe)
    st = ControllerState(buttons={"A", "B", "X", "Y", "RB", "BACK", "GUIDE", "LS", "RS",
                                  "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"})
    st.axes.update(left_x=-1, left_y=-1, right_x=1, right_y=1, lt=1, rt=1)
    pad.send(st)
    pad.send(st)          # unchanged: not resent (keepalive aside)
    pad.close()
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert lines[0] == {"persona": "game-controller-compatible"}
    assert lines[1] == {}                       # neutral frame sent on start
    assert len(lines[2]["buttons"]) == 9 and len(lines[2]["dpad"]) == 3
    assert lines[-1] == {}                      # released on close
    assert len(lines) == 4


def test_reports_service_failure(fake_ojd, monkeypatch):
    exe, _ = fake_ojd
    monkeypatch.setenv("FAKE_OJD_FAIL", "1")
    with pytest.raises(BackendUnavailable, match="service is not running"):
        OJDBackend(executable=exe)


def test_missing_ojd(monkeypatch):
    monkeypatch.setattr("posepad.backends.ojd.find_ojd", lambda: None)
    with pytest.raises(BackendUnavailable, match="OpenJoystickDriver"):
        OJDBackend()


def test_profile_output_options(tmp_path):
    p = parse_profile({"output": {"backend": "ojd", "persona": "generic"}}, tmp_path / "p.yaml")
    assert p.output == "ojd" and p.output_options == {"persona": "generic"}
    with pytest.raises(ConfigError, match="persona must be one of"):
        parse_profile({"output": {"backend": "ojd", "persona": "xbox"}}, tmp_path / "p.yaml")


def test_auto_prefers_ojd_on_macos(monkeypatch):
    from posepad import backends
    monkeypatch.setattr(backends.sys, "platform", "darwin")
    assert backends.auto_order() == ("ojd",)
    made = []
    monkeypatch.setattr(backends, "_make", lambda name, opts=None: made.append((name, opts)) or backends.LogBackend())
    backends.create_backend("auto", need_keyboard=False, options={"persona": "generic"})
    assert made == [("ojd", {"persona": "generic"})]
