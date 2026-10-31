"""macOS virtual gamepad via OpenJoystickDriver (https://github.com/xsyetopz/OpenJoystickDriver).

macOS only lets a process publish a virtual HID gamepad if it is signed with
Apple's restricted ``com.apple.developer.hid.virtual.device`` entitlement, which
a Python interpreter does not have.  OpenJoystickDriver is a notarized app that
does, and its ``ojd virtual feed`` command publishes a virtual gamepad driven by
one JSON frame per line on stdin.  This backend keeps one feed running and
writes posepad's controller state to it.

Personas (``output: {backend: ojd, persona: ...}``):

* ``sdl-compatible`` (default) - SDL games and Steam
* ``game-controller-compatible`` - Apple's GameController framework (native Mac games)
* ``generic`` - plain HID gamepad
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import threading
import time
from collections import deque

from ..bindings import ControllerState
from . import Backend, BackendUnavailable

PERSONAS = ("sdl-compatible", "game-controller-compatible", "generic")

BUTTONS = {
    "A": "South", "B": "East", "X": "West", "Y": "North",
    "LB": "LeftShoulder", "RB": "RightShoulder", "BACK": "Back", "START": "Start",
    "GUIDE": "Guide", "LS": "LeftStickClick", "RS": "RightStickClick",
}
DPAD = {"DPAD_UP": "DpadUp", "DPAD_DOWN": "DpadDown",
        "DPAD_LEFT": "DpadLeft", "DPAD_RIGHT": "DpadRight"}

# ojd drops the gamepad after 2 s without a frame; resend unchanged state well before that.
KEEPALIVE = 0.5


def find_ojd() -> str | None:
    """``ojd`` on PATH (the app installs a link), else inside the app bundle."""
    if os.environ.get("POSEPAD_OJD"):
        return os.environ["POSEPAD_OJD"]
    found = shutil.which("ojd")
    if found:
        return found
    for app in ("/Applications/OpenJoystickDriver.app",
                os.path.expanduser("~/Applications/OpenJoystickDriver.app")):
        for candidate in glob.glob(f"{app}/Contents/**/ojd", recursive=True):
            if os.access(candidate, os.X_OK):
                return candidate
    return None


def frame(state: ControllerState) -> dict:
    """posepad state -> an ojd ``VirtualFeedFrame``."""
    out: dict = {}
    buttons = sorted(BUTTONS[b] for b in state.buttons if b in BUTTONS)
    dpad = sorted(DPAD[b] for b in state.buttons if b in DPAD)
    if buttons:
        out["buttons"] = buttons
    if dpad:
        out["dpad"] = dpad
    a = state.axes
    # posepad sticks are +y = up; ojd's are +y = down.
    axes = {
        "LeftStickX": a["left_x"], "LeftStickY": -a["left_y"],
        "RightStickX": a["right_x"], "RightStickY": -a["right_y"],
        "LeftTrigger": a["lt"], "RightTrigger": a["rt"],
    }
    axes = {k: round(v, 4) + 0.0 for k, v in axes.items() if v}
    if axes:
        out["axes"] = axes
    return out


class OJDBackend(Backend):
    name = "ojd"

    def __init__(self, persona: str = "sdl-compatible", executable: str | None = None):
        if persona not in PERSONAS:
            raise BackendUnavailable(f"unknown ojd persona {persona!r}; use one of {', '.join(PERSONAS)}")
        exe = executable or find_ojd()
        if exe is None:
            raise BackendUnavailable(
                "OpenJoystickDriver's `ojd` was not found. Install the app from "
                "https://github.com/xsyetopz/OpenJoystickDriver (or set POSEPAD_OJD)")
        self.name = f"ojd ({persona})"
        self._stderr: deque[str] = deque(maxlen=20)
        try:
            self.proc = subprocess.Popen(
                [exe, "virtual", "feed", "--as", persona],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, bufsize=1)
        except OSError as e:
            raise BackendUnavailable(f"cannot start {exe}: {e}") from None
        threading.Thread(target=self._drain, daemon=True).start()
        self._last: str | None = None
        self._sent_at = 0.0
        # Fail now, not mid-game, if the service refuses the feed.
        self._write(frame(ControllerState()), force=True)
        time.sleep(0.3)
        self._check()

    def _drain(self) -> None:
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip())

    def _check(self) -> None:
        code = self.proc.poll()
        if code is not None:
            detail = "; ".join(self._stderr) or "no output"
            hint = " (is the OpenJoystickDriver app running and allowed in Accessibility?)"
            raise BackendUnavailable(f"`ojd virtual feed` exited with code {code}: {detail}{hint}")

    def _write(self, data: dict, force: bool = False) -> None:
        line = json.dumps(data, separators=(",", ":"))
        now = time.monotonic()
        if not force and line == self._last and now - self._sent_at < KEEPALIVE:
            return
        try:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self._check()
            raise
        self._last, self._sent_at = line, now

    def send(self, state: ControllerState) -> None:
        self._write(frame(state))

    def close(self) -> None:
        try:
            self._write({}, force=True)
            self.proc.stdin.close()   # end of input: ojd plays the last frame and removes the pad
            self.proc.wait(timeout=2)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            self.proc.kill()
