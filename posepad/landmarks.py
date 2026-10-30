"""Landmark names and the body-relative coordinate frame used by expressions.

Pose estimators report landmarks in image coordinates (x right, y down, in
0..1 of the frame).  Thresholds written in those units break as soon as the
player steps closer to or further from the camera, so every frame is converted
into a *body frame* before any gesture is evaluated:

* origin  - midpoint between the shoulders
* unit    - shoulder width (so ``1.0`` is "one shoulder width")
* +x      - the player's own right (a raised right arm has ``x > 0``)
* +y      - up
* +z      - towards the camera

Velocities and displacements (``vx``, ``dx`` ...) are measured in the same
units but are *not* relative to the shoulders, so whole-body moves like jumps,
ducks and side-steps show up on every point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# MediaPipe BlazePose topology (33 points). Other estimators map onto this.
LANDMARK_NAMES: tuple[str, ...] = (
    "nose",
    "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear",
    "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_pinky", "right_pinky",
    "left_index", "right_index",
    "left_thumb", "right_thumb",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
    "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
)
LANDMARK_INDEX = {name: i for i, name in enumerate(LANDMARK_NAMES)}

# Virtual points computed as the mean of real landmarks.
DERIVED_POINTS: dict[str, tuple[str, ...]] = {
    "shoulder_mid": ("left_shoulder", "right_shoulder"),
    "hip_mid": ("left_hip", "right_hip"),
    "torso": ("left_shoulder", "right_shoulder", "left_hip", "right_hip"),
    "knee_mid": ("left_knee", "right_knee"),
    "ankle_mid": ("left_ankle", "right_ankle"),
    "head": ("nose", "left_ear", "right_ear"),
}

ALL_POINTS: tuple[str, ...] = LANDMARK_NAMES + tuple(DERIVED_POINTS)

# Pairs drawn by the overlay.
SKELETON_EDGES: tuple[tuple[str, str], ...] = (
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
    ("nose", "left_eye"), ("nose", "right_eye"),
)


@dataclass
class RawPose:
    """One estimator result. ``points`` is (33, 3) image coords, ``visibility`` (33,)."""

    points: np.ndarray
    visibility: np.ndarray
    timestamp: float


@dataclass
class Point:
    """A point in the body frame, as seen by expressions."""

    x: float
    y: float
    z: float
    visibility: float
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0

    @property
    def speed(self) -> float:
        return math.sqrt(self.vx * self.vx + self.vy * self.vy + self.vz * self.vz)

    @property
    def visible(self) -> bool:
        return self.visibility >= 0.5


@dataclass
class BodyFrame:
    """Normalised pose for one video frame plus per-point velocities."""

    timestamp: float
    positions: np.ndarray            # (N, 3) relative to shoulder_mid, for ALL_POINTS
    visibility: np.ndarray           # (N,)
    absolute: np.ndarray             # (N, 3) camera-anchored, same units/orientation
    scale: float = 1.0               # shoulder width in image units
    velocities: np.ndarray = field(default_factory=lambda: np.zeros((len(ALL_POINTS), 3)))
    displacement: np.ndarray = field(default_factory=lambda: np.zeros((len(ALL_POINTS), 3)))

    def point(self, name: str) -> Point:
        i = POINT_INDEX[name]
        p, v, d = self.positions[i], self.velocities[i], self.displacement[i]
        return Point(float(p[0]), float(p[1]), float(p[2]), float(self.visibility[i]),
                     float(v[0]), float(v[1]), float(v[2]),
                     float(d[0]), float(d[1]), float(d[2]))


POINT_INDEX = {name: i for i, name in enumerate(ALL_POINTS)}
_DERIVED_IDX = [[LANDMARK_INDEX[n] for n in parts] for parts in DERIVED_POINTS.values()]


def to_body_frame(raw: RawPose, aspect: float = 1.0,
                  scale: float | None = None) -> BodyFrame | None:
    """Convert image-space landmarks to the body frame.

    ``aspect`` is frame width / height; it is applied so that a shoulder width
    measures the same horizontally and vertically.  Returns ``None`` when the
    shoulders are not visible, since the frame cannot be anchored without them.
    """
    pts = np.asarray(raw.points, dtype=float).copy()
    vis = np.asarray(raw.visibility, dtype=float)
    pts[:, 0] *= aspect
    pts[:, 2] *= aspect  # MediaPipe z uses roughly the same scale as x

    derived = np.array([pts[idx].mean(axis=0) for idx in _DERIVED_IDX])
    derived_vis = np.array([vis[idx].min() for idx in _DERIVED_IDX])
    allp = np.vstack([pts, derived])
    allv = np.concatenate([vis, derived_vis])

    ls, rs = LANDMARK_INDEX["left_shoulder"], LANDMARK_INDEX["right_shoulder"]
    if min(vis[ls], vis[rs]) < 0.3:
        return None
    if scale is None:
        scale = shoulder_width(raw, aspect)
    if scale < 1e-4:
        return None

    # Image x grows towards the player's left (camera faces them), y grows down,
    # MediaPipe z grows away from the camera: flip all three.
    absolute = allp / -scale
    origin = (absolute[ls] + absolute[rs]) / 2.0
    return BodyFrame(raw.timestamp, absolute - origin, allv, absolute, scale=scale)


def shoulder_width(raw: RawPose, aspect: float = 1.0) -> float:
    ls, rs = LANDMARK_INDEX["left_shoulder"], LANDMARK_INDEX["right_shoulder"]
    d = np.asarray(raw.points[ls, :2], dtype=float) - np.asarray(raw.points[rs, :2], dtype=float)
    d[0] *= aspect
    return float(np.linalg.norm(d))
