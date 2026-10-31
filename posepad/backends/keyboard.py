"""Keyboard output via ``pynput`` for games that only read the keyboard."""

from __future__ import annotations

from ..bindings import ControllerState
from . import Backend, BackendUnavailable


def parse_key(name: str):
    """``"space"``, ``"left"``, ``"f5"``, ``"w"`` -> a pynput key."""
    from pynput.keyboard import Key, KeyCode
    n = name.strip().lower()
    if len(n) == 1:
        return KeyCode.from_char(n)
    alias = {"ctrl": "ctrl_l", "shift": "shift_l", "alt": "alt_l", "return": "enter",
             "escape": "esc", "pgup": "page_up", "pgdn": "page_down"}.get(n, n)
    try:
        return getattr(Key, alias)
    except AttributeError:
        raise ValueError(f"unknown key {name!r}") from None


class KeyboardBackend(Backend):
    name = "keyboard"

    def __init__(self):
        from ..macos import accessibility_help, accessibility_trusted
        if accessibility_trusted() is False:
            raise BackendUnavailable(accessibility_help())
        try:
            from pynput.keyboard import Controller
            self.kb = Controller()
        except Exception as err:
            raise BackendUnavailable(f"pynput keyboard unavailable: {err}") from None
        self._down: dict[str, object] = {}

    def send(self, state: ControllerState) -> None:
        for name in list(self._down):
            if name not in state.keys:
                self.kb.release(self._down.pop(name))
        for name in state.keys:
            if name not in self._down:
                k = parse_key(name)
                self.kb.press(k)
                self._down[name] = k

    def close(self) -> None:
        self.send(ControllerState())
