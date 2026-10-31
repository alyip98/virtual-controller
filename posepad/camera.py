"""Webcam capture on a background thread so processing always sees the newest frame."""

from __future__ import annotations

import sys
import threading
import time

import numpy as np


class Camera:
    def __init__(self, device: int | str = 0, width: int = 640, height: int = 480, fps: int = 30):
        import cv2
        self._cv2 = cv2
        self.cap = cv2.VideoCapture(device)
        if not self.cap.isOpened():
            msg = f"cannot open camera {device!r} (try --camera 1, or a video file)"
            if sys.platform == "darwin":
                from .macos import camera_help
                msg += "\n" + camera_help()
            raise RuntimeError(msg)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.is_file = isinstance(device, str) and not device.isdigit()
        self._fps = self.cap.get(cv2.CAP_PROP_FPS) or fps
        self._frame: np.ndarray | None = None
        self._stamp = 0.0
        self._seq = 0
        self._read_seq = 0
        self._cond = threading.Condition()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        start = time.monotonic()
        n = 0
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                with self._cond:
                    self._running = False
                    self._cond.notify_all()
                return
            n += 1
            # Video files have no real clock: use their nominal frame rate.
            stamp = n / self._fps if self.is_file else time.monotonic() - start
            with self._cond:
                self._frame, self._stamp = frame, stamp
                self._seq += 1
                self._cond.notify_all()
            if self.is_file:
                # Pace files so the consumer sees every frame.
                with self._cond:
                    self._cond.wait_for(lambda: self._read_seq >= self._seq or not self._running)

    def read(self, timeout: float = 2.0) -> tuple[np.ndarray, float] | None:
        """Block for the next new frame; returns (BGR image, seconds) or None at the end."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._seq > self._read_seq or not self._running,
                                       timeout):
                return None
            if self._frame is None or self._seq == self._read_seq:
                return None
            self._read_seq = self._seq
            self._cond.notify_all()
            return self._frame, self._stamp

    def close(self) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()
        self._thread.join(timeout=1)
        self.cap.release()
