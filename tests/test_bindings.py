import pytest

from posepad.bindings import Binding, BindingSet
from posepad.gestures import GestureState


def run(bindings, seq, analog=None):
    bs = BindingSet(bindings, analog or {})
    return [bs.update(states, t) for t, states in seq]


def S(active, value=None):
    return GestureState(active=active, value=float(active) if value is None else value, tracked=True)


def test_hold_tap_toggle():
    bs = [Binding("g", button="A"), Binding("g", button="B", mode="tap", tap_time=0.1),
          Binding("g", button="X", mode="toggle")]
    seq = [(0.0, {"g": S(True)}), (0.05, {"g": S(True)}), (0.2, {"g": S(True)}),
           (0.3, {"g": S(False)}), (0.4, {"g": S(True)})]
    out = [o.buttons for o in run(bs, seq)]
    assert out[0] == {"A", "B", "X"}
    assert out[1] == {"A", "B", "X"}
    assert out[2] == {"A", "X"}          # tap expired while still held
    assert out[3] == {"X"}               # toggle stays on
    assert out[4] == {"A", "B"}          # second rising edge toggles X off, taps B


def test_axes_sum_and_clamp():
    bs = [Binding("l", axis="left_x", value=-1.0), Binding("r", axis="left_x", value=1.0),
          Binding("lean", axis="left_x", scale=2.0), Binding("g", axis="rt")]
    o = run(bs, [(0, {"l": S(True), "r": S(False), "lean": S(True, 0.2), "g": S(True)})],
            analog={"lean": True})[0]
    assert o.axes["left_x"] == pytest.approx(-0.6)
    assert o.axes["rt"] == 1.0
    o = run(bs, [(0, {"l": S(False), "r": S(True), "lean": S(True, 0.9), "g": S(False)})],
            analog={"lean": True})[0]
    assert o.axes["left_x"] == 1.0       # clamped


def test_analog_deadzone_and_invert():
    b = Binding("lean", axis="left_y", deadzone=0.2, invert=True)
    o = run([b], [(0, {"lean": S(True, 0.1)})], {"lean": True})[0]
    assert o.axes["left_y"] == 0.0
    o = run([b], [(0, {"lean": S(True, 0.5)})], {"lean": True})[0]
    assert o.axes["left_y"] == pytest.approx(-0.5)
