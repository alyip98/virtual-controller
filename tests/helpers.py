"""Synthetic poses for tests: describe a pose in body units, get image-space landmarks."""

from __future__ import annotations

import numpy as np

from posepad.landmarks import LANDMARK_INDEX, LANDMARK_NAMES, RawPose

# A standing player in body units (+x = player's right, +y = up), arms down.
STANDING = {
    "nose": (0.0, 0.75), "left_eye_inner": (-0.05, 0.8), "left_eye": (-0.08, 0.8),
    "left_eye_outer": (-0.11, 0.8), "right_eye_inner": (0.05, 0.8), "right_eye": (0.08, 0.8),
    "right_eye_outer": (0.11, 0.8), "left_ear": (-0.18, 0.75), "right_ear": (0.18, 0.75),
    "mouth_left": (-0.05, 0.65), "mouth_right": (0.05, 0.65),
    "left_shoulder": (-0.5, 0.0), "right_shoulder": (0.5, 0.0),
    "left_elbow": (-0.6, -0.75), "right_elbow": (0.6, -0.75),
    "left_wrist": (-0.65, -1.4), "right_wrist": (0.65, -1.4),
    "left_pinky": (-0.66, -1.55), "right_pinky": (0.66, -1.55),
    "left_index": (-0.65, -1.56), "right_index": (0.65, -1.56),
    "left_thumb": (-0.6, -1.5), "right_thumb": (0.6, -1.5),
    "left_hip": (-0.3, -1.4), "right_hip": (0.3, -1.4),
    "left_knee": (-0.3, -2.4), "right_knee": (0.3, -2.4),
    "left_ankle": (-0.3, -3.3), "right_ankle": (0.3, -3.3),
    "left_heel": (-0.3, -3.4), "right_heel": (0.3, -3.4),
    "left_foot_index": (-0.3, -3.45), "right_foot_index": (0.3, -3.45),
}


def pose(t: float = 0.0, offset=(0.0, 0.0), width: float = 0.15, aspect: float = 1.0,
         hidden=(), **moves) -> RawPose:
    """Build a RawPose.

    ``moves`` override body-unit positions (``right_wrist=(0.6, 1.2)``),
    ``offset`` shifts the whole body in body units (+y = up),
    ``width`` is the shoulder width as a fraction of the image width.
    """
    body = dict(STANDING)
    for k, v in moves.items():
        body[k] = v
    pts = np.zeros((len(LANDMARK_NAMES), 3))
    vis = np.ones(len(LANDMARK_NAMES))
    for name, (bx, by) in body.items():
        bx, by = bx + offset[0], by + offset[1]
        i = LANDMARK_INDEX[name]
        # camera faces the player: player's right is image left; image y is down
        pts[i] = (0.5 - bx * width / aspect, 0.4 - by * width, 0.0)
    for name in hidden:
        vis[LANDMARK_INDEX[name]] = 0.0
    return RawPose(pts, vis, t)
