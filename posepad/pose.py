"""Pose estimation backend (MediaPipe Pose Landmarker).

Anything that yields 33 BlazePose-ordered landmarks can be plugged in by
implementing :class:`PoseEstimator`.
"""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path

import numpy as np

from .landmarks import LANDMARK_NAMES, RawPose

log = logging.getLogger(__name__)

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
             "pose_landmarker_{0}/float16/latest/pose_landmarker_{0}.task")


class PoseEstimator:
    def process(self, rgb: np.ndarray, timestamp: float) -> RawPose | None:
        raise NotImplementedError

    def close(self) -> None:
        pass


def model_path(variant: str) -> Path:
    """Download (once) and return the Pose Landmarker model file."""
    cache = Path(os.environ.get("POSEPAD_CACHE", Path.home() / ".cache" / "posepad"))
    path = cache / f"pose_landmarker_{variant}.task"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        url = MODEL_URL.format(variant)
        log.warning("downloading pose model %s -> %s", url, path)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(path)
    return path


class MediaPipeEstimator(PoseEstimator):
    def __init__(self, model: str = "lite", min_detection_confidence: float = 0.5,
                 min_tracking_confidence: float = 0.5, model_file: str | None = None):
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python import vision
        except ImportError as e:
            raise RuntimeError("mediapipe is not installed: pip install mediapipe") from e
        self._mp = mp
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_file or model_path(model))),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=min_detection_confidence,
            min_pose_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._last_ms = -1

    def process(self, rgb: np.ndarray, timestamp: float) -> RawPose | None:
        ms = max(int(timestamp * 1000), self._last_ms + 1)  # must strictly increase
        self._last_ms = ms
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB,
                               data=np.ascontiguousarray(rgb))
        result = self._landmarker.detect_for_video(image, ms)
        if not result.pose_landmarks:
            return None
        lms = result.pose_landmarks[0]
        if len(lms) < len(LANDMARK_NAMES):
            return None
        pts = np.array([[lm.x, lm.y, lm.z] for lm in lms[:len(LANDMARK_NAMES)]], dtype=float)
        vis = np.array([_vis(lm) for lm in lms[:len(LANDMARK_NAMES)]], dtype=float)
        return RawPose(pts, vis, timestamp)

    def close(self) -> None:
        self._landmarker.close()


def _vis(lm) -> float:
    v = getattr(lm, "visibility", None)
    p = getattr(lm, "presence", None)
    v = 1.0 if v is None else v
    return float(min(v, p) if p is not None else v)
