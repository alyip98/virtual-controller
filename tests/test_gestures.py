import numpy as np
import pytest

from helpers import pose
from posepad.expr import Expression
from posepad.gestures import ExprGesture, GestureEngine, SequenceGesture, TemplateGesture
from posepad.landmarks import to_body_frame
from posepad.templates import PoseTemplate, resolve_joints

UP = {"right_wrist": (0.6, 1.2)}


def frame(t=0.0, **moves):
    return to_body_frame(pose(t, **moves))


def engine(**gestures):
    return GestureEngine(gestures)


def test_static_pose():
    g = ExprGesture("up", when=Expression("right_wrist.y > head.y"))
    e = engine(up=g)
    assert not e.update(frame(), 0)["up"].active
    assert e.update(frame(**UP), 0.1)["up"].active


def test_hold_debounces():
    e = engine(up=ExprGesture("up", hold=0.2, when=Expression("right_wrist.y > head.y")))
    assert not e.update(frame(**UP), 0.0)["up"].active
    assert not e.update(frame(**UP), 0.1)["up"].active
    assert e.update(frame(**UP), 0.25)["up"].active


def test_min_on_and_cooldown():
    e = engine(up=ExprGesture("up", min_on=0.3, cooldown=0.5,
                              when=Expression("right_wrist.y > head.y")))
    assert e.update(frame(**UP), 0.0)["up"].active
    assert e.update(frame(), 0.1)["up"].active        # held by min_on
    assert not e.update(frame(), 0.35)["up"].active
    assert not e.update(frame(**UP), 0.5)["up"].active  # cooling down
    assert e.update(frame(**UP), 0.9)["up"].active


def test_release_hysteresis():
    g = ExprGesture("up", when=Expression("right_wrist.y > 0.5"),
                    release=Expression("right_wrist.y < 0"))
    e = engine(up=g)
    assert e.update(frame(right_wrist=(0.6, 0.6)), 0)["up"].active
    assert e.update(frame(right_wrist=(0.6, 0.2)), 0.1)["up"].active   # between thresholds
    assert not e.update(frame(right_wrist=(0.6, -0.2)), 0.2)["up"].active


def test_hidden_points_mean_inactive_not_crash():
    e = engine(up=ExprGesture("up", when=Expression("right_wrist.y > head.y")))
    st = e.update(frame(hidden=["right_wrist"], **UP), 0)["up"]
    assert not st.active and not st.tracked
    st = e.update(None, 0.1)["up"]
    assert not st.active and not st.tracked


def test_analog_value_and_composition():
    lean = ExprGesture("lean", value_expr=Expression("clamp(-hip_mid.x * 3)"), threshold=0.5)
    right = ExprGesture("right", when=Expression("lean > 0.5", ["lean"]))
    e = engine(right=right, lean=lean)   # order in the dict does not matter
    hips_left = {"left_hip": (-0.6, -1.4), "right_hip": (0.0, -1.4)}  # upper body leans right
    st = e.update(frame(**hips_left), 0)
    assert st["lean"].value == pytest.approx(0.9)
    assert st["right"].active


def test_cycle_is_reported():
    from posepad.expr import ExpressionError
    a = ExprGesture("a", when=Expression("b", ["b"]))
    b = ExprGesture("b", when=Expression("a", ["a"]))
    with pytest.raises(ExpressionError, match="loop"):
        engine(a=a, b=b)


def test_sequence_wave():
    out, left = "right_wrist.x > 0.9", "right_wrist.x < 0.3"
    g = SequenceGesture("wave", steps=[Expression(out), Expression(left), Expression(out)], within=1.0)
    e = engine(wave=g)
    xs = [1.0, 1.0, 0.6, 0.2, 0.2, 0.6, 1.0]
    states = [e.update(frame(right_wrist=(x, 0.5)), i * 0.1)["wave"].active for i, x in enumerate(xs)]
    assert states[-1] and not any(states[:-1])


def test_sequence_times_out():
    out, left = "right_wrist.x > 0.9", "right_wrist.x < 0.3"
    g = SequenceGesture("wave", steps=[Expression(out), Expression(left), Expression(out)], within=0.5)
    e = engine(wave=g)
    for i, x in enumerate([1.0, 0.2]):
        e.update(frame(right_wrist=(x, 0.5)), i * 0.1)
    assert not e.update(frame(right_wrist=(1.0, 0.5)), 2.0)["wave"].active


def test_template_matching():
    t_pose = {"left_elbow": (-1.2, 0), "left_wrist": (-1.9, 0),
              "right_elbow": (1.2, 0), "right_wrist": (1.9, 0)}
    frames = [frame(i * 0.03, **t_pose) for i in range(10)]
    tpl = PoseTemplate.from_frames("t", frames, resolve_joints("arms"))
    e = engine(t=TemplateGesture("t", template=tpl, tolerance=0.3))
    st = e.update(frame(**t_pose), 0)["t"]
    assert st.active and st.value == pytest.approx(1.0)
    assert not e.update(frame(), 0.1)["t"].active


def test_template_roundtrip(tmp_path):
    tpl = PoseTemplate("x", ("nose", "left_wrist"), np.array([[0.0, 0.7], [-0.6, -1.4]]))
    tpl.save(tmp_path / "x.json")
    back = PoseTemplate.load(tmp_path / "x.json")
    assert back.joints == tpl.joints
    assert np.allclose(back.positions, tpl.positions)
