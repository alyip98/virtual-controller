"""``posepad record``: capture a pose from the camera and save it as a template."""

from __future__ import annotations

import time
from pathlib import Path

from .landmarks import BodyFrame
from .templates import PoseTemplate, resolve_joints
from .tracker import PoseTracker


def record_pose(name: str, out_dir: Path, joints: str = "body", countdown: float = 3.0,
                duration: float = 1.5, camera: int | str = 0, mirror: bool = True,
                model: str = "lite", preview: bool = True) -> Path:
    import cv2

    from .camera import Camera
    from .overlay import AMBER, GREEN, Overlay
    from .pose import MediaPipeEstimator

    joint_names = resolve_joints(joints)
    cam = Camera(camera)
    est = MediaPipeEstimator(model)
    overlay = Overlay(mirror=mirror, title="posepad - record") if preview else None
    tracker = PoseTracker()
    frames: list[BodyFrame] = []
    start: float | None = None
    try:
        while True:
            got = cam.read()
            if got is None:
                raise RuntimeError("camera stopped")
            bgr, t = got
            h, w = bgr.shape[:2]
            raw = est.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), t)
            frame = tracker.update(raw, t, w / h)
            now = time.monotonic()
            if start is None and frame is not None:
                start = now  # countdown begins once the player is visible
            phase = "wait" if start is None else (
                "count" if now - start < countdown else
                "rec" if now - start < countdown + duration else "done")
            if phase == "rec" and frame is not None:
                frames.append(frame)
            if overlay:
                if phase == "wait":
                    status = [("step into view...", AMBER)]
                elif phase == "count":
                    status = [(f"get into pose '{name}': {countdown - (now - start):.1f}", AMBER)]
                else:
                    status = [(f"recording '{name}' - hold still", GREEN)]
                img = overlay.draw(bgr, raw, {}, {}, _empty(), status, [])
                if overlay.show(img) in (ord("q"), 27):
                    raise KeyboardInterrupt
            if phase == "done":
                break
    finally:
        cam.close()
        est.close()
        if overlay:
            overlay.close()

    tpl = PoseTemplate.from_frames(name, frames, joint_names)
    path = Path(out_dir) / f"{name}.json"
    tpl.save(path)
    return path


def _empty():
    from .bindings import ControllerState
    return ControllerState()
