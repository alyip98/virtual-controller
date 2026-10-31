"""The live loop: camera -> pose -> gestures -> virtual controller."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .backends import Backend, create_backend
from .config import ConfigError, Profile, load_profile
from .expr import Expression
from .pipeline import Pipeline
from .session import SessionWriter

log = logging.getLogger(__name__)

HELP = "q quit | p pause output | c recalibrate | r reload"


class ProfileWatcher:
    """Reloads the profile when it, or a recorded pose, changes on disk."""

    def __init__(self, profile: Profile):
        self.path = profile.path
        self.poses_dir = profile.poses_dir
        self._stamp = self._mtime()
        self._next_check = 0.0

    def _mtime(self) -> tuple:
        files = [self.path]
        if self.poses_dir and self.poses_dir.is_dir():
            files += sorted(self.poses_dir.glob("*.json"))
        return tuple((str(f), f.stat().st_mtime) for f in files if f.exists())

    def poll(self, now: float, force: bool = False) -> Profile | ConfigError | None:
        if not force and now < self._next_check:
            return None
        self._next_check = now + 1.0
        stamp = self._mtime()
        if stamp == self._stamp and not force:
            return None
        self._stamp = stamp
        try:
            return load_profile(self.path)
        except ConfigError as e:
            return e


def run(profile_path: str | Path, output: str | None = None, preview: bool = True,
        camera: str | int | None = None, watch: list[str] | None = None,
        save_session: str | None = None, start_paused: bool = False) -> None:
    import cv2

    from .camera import Camera
    from .pose import MediaPipeEstimator

    profile = load_profile(profile_path)
    cam_cfg = profile.camera
    device = cam_cfg.device if camera is None else camera
    if isinstance(device, str) and device.isdigit():
        device = int(device)
    cam = Camera(device, cam_cfg.width, cam_cfg.height, cam_cfg.fps)
    estimator = MediaPipeEstimator(profile.pose.model, profile.pose.min_detection_confidence,
                                   profile.pose.min_tracking_confidence)
    backend: Backend = create_backend(output or profile.output, profile.needs_keyboard,
                                      profile.needs_gamepad, profile.output_options)
    print(f"posepad: profile '{profile.name}', output -> {backend.name}")
    print(f"posepad: {HELP}")

    overlay = None
    if preview:
        from .overlay import Overlay
        overlay = Overlay(mirror=cam_cfg.mirror, title=f"posepad - {profile.name}")

    pipeline: Pipeline | None = None
    watcher = ProfileWatcher(profile)
    extra_watch = [Expression(w, profile.gestures) for w in (watch or [])]
    writer = None
    paused = start_paused
    message, message_until = "", 0.0
    fps, last_t = 0.0, None

    try:
        while True:
            got = cam.read()
            if got is None:
                break
            bgr, t = got
            if pipeline is None:
                h, w = bgr.shape[:2]
                pipeline = Pipeline(profile, aspect=w / h)
                if save_session:
                    writer = SessionWriter(save_session, w / h)
            raw = estimator.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), t)
            if writer:
                writer.write(t, raw)
            result = pipeline.step(raw, t)
            backend.send(result.output if not paused else _neutral())

            if last_t is not None and t > last_t:
                fps = 0.9 * fps + 0.1 / (t - last_t)
            last_t = t

            reloaded = watcher.poll(time.monotonic())
            key = 0
            if overlay is not None:
                status = _status(profile, backend, pipeline, paused, fps, result.frame is not None)
                if message and time.monotonic() < message_until:
                    status.append((message, (0, 190, 255)))
                watch_vals = [(e.source, pipeline.engine.evaluate(e))
                              for e in profile.watch + extra_watch]
                img = overlay.draw(bgr, raw, result.states, pipeline.engine.gestures,
                                   result.output, status, watch_vals)
                key = overlay.show(img)
            if key == ord("r"):
                reloaded = watcher.poll(time.monotonic(), force=True)
            if reloaded is not None:
                if isinstance(reloaded, ConfigError):
                    message = "reload failed: " + reloaded.problems[0]
                    print(f"posepad: {reloaded}")
                else:
                    profile = reloaded
                    pipeline.swap_profile(profile)
                    extra_watch = [Expression(w, profile.gestures) for w in (watch or [])]
                    message = "profile reloaded"
                    print("posepad: profile reloaded")
                message_until = time.monotonic() + 4
            if key in (ord("q"), 27):
                break
            if key == ord("p"):
                paused = not paused
            if key == ord("c"):
                pipeline.tracker.recalibrate()
    except KeyboardInterrupt:
        pass
    finally:
        backend.close()
        cam.close()
        estimator.close()
        if overlay:
            overlay.close()
        if writer:
            writer.close()


def _neutral():
    from .bindings import ControllerState
    return ControllerState()


def _status(profile, backend, pipeline, paused, fps, tracked):
    from .overlay import AMBER, GREEN, RED
    lines = [(f"{profile.name}  ->  {backend.name}   {fps:4.1f} fps", GREEN)]
    if paused:
        lines.append(("OUTPUT PAUSED (p)", RED))
    if not tracked:
        lines.append(("no player detected - step into view", AMBER))
    elif not pipeline.tracker.calibrated:
        lines.append(("calibrating: stand still in your neutral pose", AMBER))
    return lines
