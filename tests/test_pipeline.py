from pathlib import Path

from helpers import pose
from posepad.config import load_profile, parse_profile
from posepad.cli import PROFILES_DIR
from posepad.pipeline import Pipeline
from posepad.session import SessionWriter, read_session

DT = 1 / 30


def stand(pipe, seconds=1.5, t0=0.0):
    t = t0
    out = None
    while t < t0 + seconds:
        out = pipe.step(pose(t), t)
        t += DT
    return t, out


def test_starter_jump_after_calibration():
    pipe = Pipeline(load_profile(PROFILES_DIR / "starter.yaml"), aspect=1.0)
    t, out = stand(pipe)
    assert pipe.tracker.calibrated
    assert out.output.is_neutral()
    pressed = set()
    for i in range(8):  # rise ~1.2 shoulder widths in a quarter second
        y = 0.15 * (i + 1)
        res = pipe.step(pose(t, offset=(0, y)), t)
        pressed |= res.output.buttons
        t += DT
    assert "A" in pressed


def test_starter_lean_steers_and_hands_press():
    pipe = Pipeline(load_profile(PROFILES_DIR / "starter.yaml"), aspect=1.0)
    t, _ = stand(pipe)
    lean_right = {"left_hip": (-0.7, -1.3), "right_hip": (-0.1, -1.3)}
    for _ in range(20):
        res = pipe.step(pose(t, **lean_right), t)
        t += DT
    assert res.output.axes["left_x"] > 0.5
    for _ in range(10):
        res = pipe.step(pose(t, right_wrist=(0.6, 1.3)), t)
        t += DT
    assert "X" in res.output.buttons and "START" not in res.output.buttons


def test_losing_the_player_releases_everything(tmp_path):
    prof = parse_profile({"gestures": {"up": "right_wrist.y > head.y"},
                          "bindings": ["up -> A"]}, tmp_path / "p.yaml")
    pipe = Pipeline(prof, aspect=1.0)
    assert "A" in pipe.step(pose(0, right_wrist=(0.6, 1.3)), 0).output.buttons
    assert pipe.step(None, DT).output.is_neutral()


def test_session_roundtrip(tmp_path: Path):
    w = SessionWriter(tmp_path / "s.jsonl", 1.5)
    w.write(0.0, pose(0))
    w.write(0.033, None)
    w.close()
    aspect, frames = read_session(tmp_path / "s.jsonl")
    frames = list(frames)
    assert aspect == 1.5 and frames[1][1] is None
    assert frames[0][1].points.shape == (33, 3)
