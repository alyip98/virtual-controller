import pytest

from helpers import pose
from posepad.landmarks import to_body_frame


def test_body_frame_orientation():
    f = to_body_frame(pose())
    rw, lw, nose = f.point("right_wrist"), f.point("left_wrist"), f.point("nose")
    assert rw.x == pytest.approx(0.65)      # player's right is +x
    assert lw.x == pytest.approx(-0.65)
    assert nose.y == pytest.approx(0.75)    # up is +y
    assert f.point("shoulder_mid").x == pytest.approx(0.0)
    assert f.point("hip_mid").y == pytest.approx(-1.4)


@pytest.mark.parametrize("width,aspect", [(0.08, 1.0), (0.3, 1.0), (0.15, 16 / 9)])
def test_body_frame_is_scale_and_aspect_invariant(width, aspect):
    f = to_body_frame(pose(width=width, aspect=aspect), aspect=aspect)
    assert f.point("right_wrist").y == pytest.approx(-1.4)
    assert f.point("right_wrist").x == pytest.approx(0.65)


def test_body_frame_needs_shoulders():
    assert to_body_frame(pose(hidden=["left_shoulder"])) is None
