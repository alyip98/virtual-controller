"""Turns a stream of raw estimator output into smoothed body frames."""

from __future__ import annotations

import numpy as np

from .filters import OneEuroFilter
from .landmarks import POINT_INDEX, BodyFrame, RawPose, shoulder_width, to_body_frame


class PoseTracker:
    """Smooths landmarks, estimates velocity and tracks the neutral stance.

    The neutral stance is what ``dx``/``dy``/``dz`` are measured against.  It
    is captured automatically once the player has stood still for
    ``calibrate_after`` seconds, and again whenever :meth:`recalibrate` is
    called (bound to the ``c`` key in the preview window).
    """

    def __init__(self, min_cutoff: float = 1.5, beta: float = 0.3,
                 calibrate_after: float = 1.0, still_speed: float = 0.6,
                 lost_after: float = 0.5):
        self.filter = OneEuroFilter(min_cutoff, beta)
        self.calibrate_after = calibrate_after
        self.still_speed = still_speed
        self.lost_after = lost_after
        self.neutral: np.ndarray | None = None
        self._scale: float | None = None
        self._still_since: float | None = None
        self._last_seen: float | None = None

    def recalibrate(self) -> None:
        self.neutral = None
        self._still_since = None

    @property
    def calibrated(self) -> bool:
        return self.neutral is not None

    def update(self, raw: RawPose | None, timestamp: float, aspect: float = 1.0) -> BodyFrame | None:
        if raw is None:
            if self._last_seen is not None and timestamp - self._last_seen > self.lost_after:
                self.filter.reset()
                self._scale = None
            return None

        measured = shoulder_width(raw, aspect)
        if self._scale is None or self._last_seen is None:
            self._scale = measured
        else:
            # Shoulder width shrinks when turning sideways; follow it slowly.
            self._scale += 0.05 * (measured - self._scale)
        frame = to_body_frame(raw, aspect, scale=self._scale)
        if frame is None:
            return None
        self._last_seen = timestamp

        absolute = self.filter(frame.absolute, raw.timestamp)
        ls, rs = POINT_INDEX["left_shoulder"], POINT_INDEX["right_shoulder"]
        origin = (absolute[ls] + absolute[rs]) / 2.0
        frame.absolute = absolute
        frame.positions = absolute - origin
        frame.velocities = self.filter.derivative.copy()
        self._update_neutral(frame)
        if self.neutral is not None:
            frame.displacement = absolute - self.neutral
        return frame

    def _update_neutral(self, frame: BodyFrame) -> None:
        if self.neutral is not None:
            return
        torso = POINT_INDEX["torso"]
        speed = float(np.linalg.norm(frame.velocities[torso]))
        if speed > self.still_speed:
            self._still_since = None
            return
        if self._still_since is None:
            self._still_since = frame.timestamp
        elif frame.timestamp - self._still_since >= self.calibrate_after:
            self.neutral = frame.absolute.copy()
