"""Output backends: where the virtual controller input actually goes.

=========  ===================================================  ==============
backend    what it creates                                      platforms
=========  ===================================================  ==============
uinput     an Xbox 360-compatible pad via /dev/uinput (evdev)   Linux
vgamepad   an Xbox 360 pad via ViGEmBus (Windows) or uinput     Windows, Linux
keyboard   key presses only (for games without pad support)     all
log        prints state changes; nothing is sent                all
=========  ===================================================  ==============

``auto`` picks the first gamepad backend that works on this machine. Key
bindings are always routed to the keyboard backend in addition.
"""

from __future__ import annotations

import logging
import sys

from ..bindings import ControllerState

log = logging.getLogger(__name__)


class Backend:
    name = "base"

    def send(self, state: ControllerState) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class BackendUnavailable(RuntimeError):
    pass


class LogBackend(Backend):
    name = "log"

    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self._last: tuple | None = None

    def send(self, state: ControllerState) -> None:
        key = (tuple(sorted(state.buttons)), tuple(sorted(state.keys)),
               tuple(round(v, 2) for v in state.axes.values()))
        if key != self._last:
            self._last = key
            axes = " ".join(f"{k}={v:+.2f}" for k, v in state.axes.items() if v)
            parts = [" ".join(sorted(state.buttons)), axes,
                     " ".join(f"[{k}]" for k in sorted(state.keys))]
            print("pad:", " | ".join(p for p in parts if p) or "(neutral)", file=self.stream)


class MultiBackend(Backend):
    def __init__(self, backends: list[Backend]):
        self.backends = backends
        self.name = "+".join(b.name for b in backends)

    def send(self, state: ControllerState) -> None:
        for b in self.backends:
            b.send(state)

    def close(self) -> None:
        for b in self.backends:
            b.close()


def _make(name: str) -> Backend:
    if name == "log":
        return LogBackend()
    if name == "uinput":
        from .uinput import UInputBackend
        return UInputBackend()
    if name == "vgamepad":
        from .vgamepad_backend import VGamepadBackend
        return VGamepadBackend()
    if name == "keyboard":
        from .keyboard import KeyboardBackend
        return KeyboardBackend()
    raise BackendUnavailable(f"unknown backend {name!r}")


GAMEPAD_BACKENDS = ("uinput", "vgamepad", "log")


def create_backend(name: str, need_keyboard: bool, need_gamepad: bool = True) -> Backend:
    """Build the backend(s) a profile needs.  ``name`` may be ``auto``."""
    backends: list[Backend] = []
    if need_gamepad or name == "log":
        if name == "auto":
            order = ("vgamepad", "uinput") if sys.platform == "win32" else ("uinput", "vgamepad")
            errors = []
            for candidate in order:
                try:
                    backends.append(_make(candidate))
                    break
                except BackendUnavailable as e:
                    errors.append(f"  {candidate}: {e}")
            else:
                log.warning("no virtual gamepad backend available, logging instead:\n%s",
                            "\n".join(errors))
                backends.append(LogBackend())
        elif name != "keyboard":
            backends.append(_make(name))
    if need_keyboard or name == "keyboard":
        backends.append(_make("keyboard"))
    return backends[0] if len(backends) == 1 else MultiBackend(backends)
