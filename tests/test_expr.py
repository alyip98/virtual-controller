import pytest

from posepad.expr import Expression, ExpressionError, angle, direction, remap
from posepad.landmarks import Point


def P(x, y):
    return Point(x, y, 0.0, 1.0)


def test_evaluates_points_and_functions():
    with pytest.raises(ExpressionError, match="unknown body point 'a'"):
        Expression("a.y > 0", ["a"])
    e = Expression("angle(left_shoulder, left_elbow, left_wrist) > 170")
    assert e.evaluate({"left_shoulder": P(0, 0), "left_elbow": P(1, 0), "left_wrist": P(2, 0)})
    assert e.points == {"left_shoulder", "left_elbow", "left_wrist"}


def test_gesture_names_are_tracked_as_dependencies():
    e = Expression("jump and not crouch", ["jump", "crouch"])
    assert e.names == {"jump", "crouch"}
    assert e.evaluate({"jump": True, "crouch": False}) is True


@pytest.mark.parametrize("src", [
    "__import__('os')",
    "nose.__class__",
    "open('x')",
    "[1, 2]",
    "'text'",
    "lambda: 1",
    "nose.x if (y := 1) else 0",
])
def test_rejects_unsafe_or_unknown_syntax(src):
    with pytest.raises(ExpressionError):
        Expression(src)


def test_suggests_close_names():
    with pytest.raises(ExpressionError, match="right_wrist"):
        Expression("rigth_wrist.y > 0")
    with pytest.raises(ExpressionError, match="'vy'"):
        Expression("nose.vyy > 0")


def test_helpers():
    assert angle(P(0, 1), P(0, 0), P(1, 0)) == pytest.approx(90)
    assert direction(P(0, 0), P(0, 1)) == pytest.approx(90)
    assert direction(P(0, 0), P(1, -1)) == pytest.approx(-45)
    assert remap(5, 0, 10) == pytest.approx(0.5)
    assert remap(50, 0, 10) == 1.0
