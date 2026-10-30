"""Virtual Xbox 360 pad via the ``vgamepad`` package.

On Windows this requires the ViGEmBus driver (the vgamepad installer offers
it); on Linux vgamepad itself uses uinput.
"""

from __future__ import annotations

from ..bindings import ControllerState
from . import Backend, BackendUnavailable


class VGamepadBackend(Backend):
    name = "vgamepad"

    def __init__(self):
        try:
            import vgamepad as vg
        except Exception as err:  # vgamepad raises various errors when the driver is missing
            raise BackendUnavailable(f"vgamepad unavailable: {err}") from None
        try:
            self.pad = vg.VX360Gamepad()
        except Exception as err:
            raise BackendUnavailable(f"could not create virtual pad: {err}") from None
        B = vg.XUSB_BUTTON
        self.map = {
            "A": B.XUSB_GAMEPAD_A, "B": B.XUSB_GAMEPAD_B, "X": B.XUSB_GAMEPAD_X,
            "Y": B.XUSB_GAMEPAD_Y, "LB": B.XUSB_GAMEPAD_LEFT_SHOULDER,
            "RB": B.XUSB_GAMEPAD_RIGHT_SHOULDER, "BACK": B.XUSB_GAMEPAD_BACK,
            "START": B.XUSB_GAMEPAD_START, "GUIDE": B.XUSB_GAMEPAD_GUIDE,
            "LS": B.XUSB_GAMEPAD_LEFT_THUMB, "RS": B.XUSB_GAMEPAD_RIGHT_THUMB,
            "DPAD_UP": B.XUSB_GAMEPAD_DPAD_UP, "DPAD_DOWN": B.XUSB_GAMEPAD_DPAD_DOWN,
            "DPAD_LEFT": B.XUSB_GAMEPAD_DPAD_LEFT, "DPAD_RIGHT": B.XUSB_GAMEPAD_DPAD_RIGHT,
        }
        self._last = None

    def send(self, state: ControllerState) -> None:
        key = (frozenset(state.buttons), tuple(state.axes.values()))
        if key == self._last:
            return
        self._last = key
        for name, btn in self.map.items():
            if name in state.buttons:
                self.pad.press_button(button=btn)
            else:
                self.pad.release_button(button=btn)
        a = state.axes
        self.pad.left_joystick_float(x_value_float=a["left_x"], y_value_float=a["left_y"])
        self.pad.right_joystick_float(x_value_float=a["right_x"], y_value_float=a["right_y"])
        self.pad.left_trigger_float(value_float=a["lt"])
        self.pad.right_trigger_float(value_float=a["rt"])
        self.pad.update()

    def close(self) -> None:
        self.pad.reset()
        self.pad.update()
