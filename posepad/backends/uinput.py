"""Linux virtual Xbox 360 pad through /dev/uinput (needs python-evdev).

The device uses the Xbox 360 vendor/product IDs and the same event codes as
the kernel ``xpad`` driver, so SDL, Steam and most games map it correctly
without extra configuration.  Write access to /dev/uinput is required:

    sudo modprobe uinput
    sudo usermod -aG input $USER   # and add a udev rule, see README
"""

from __future__ import annotations

from ..bindings import ControllerState
from . import Backend, BackendUnavailable

try:
    from evdev import AbsInfo, UInput, ecodes as e
except ImportError:  # pragma: no cover - depends on the platform
    e = None

STICK = 32767


class UInputBackend(Backend):
    name = "uinput"

    def __init__(self):
        if e is None:
            raise BackendUnavailable("python-evdev is not installed (pip install evdev)")
        self.buttons = {
            "A": e.BTN_A, "B": e.BTN_B, "X": e.BTN_X, "Y": e.BTN_Y,
            "LB": e.BTN_TL, "RB": e.BTN_TR, "BACK": e.BTN_SELECT, "START": e.BTN_START,
            "GUIDE": e.BTN_MODE, "LS": e.BTN_THUMBL, "RS": e.BTN_THUMBR,
        }
        stick = AbsInfo(0, -STICK - 1, STICK, 16, 128, 0)
        trigger = AbsInfo(0, 0, 255, 0, 0, 0)
        hat = AbsInfo(0, -1, 1, 0, 0, 0)
        caps = {
            e.EV_KEY: list(self.buttons.values()),
            e.EV_ABS: [
                (e.ABS_X, stick), (e.ABS_Y, stick), (e.ABS_RX, stick), (e.ABS_RY, stick),
                (e.ABS_Z, trigger), (e.ABS_RZ, trigger),
                (e.ABS_HAT0X, hat), (e.ABS_HAT0Y, hat),
            ],
        }
        try:
            self.dev = UInput(caps, name="Microsoft X-Box 360 pad (posepad)",
                              vendor=0x045E, product=0x028E, version=0x110, bustype=e.BUS_USB)
        except (OSError, PermissionError) as err:
            raise BackendUnavailable(f"cannot open /dev/uinput ({err}); see README") from None
        self._last: dict[tuple[int, int], int] = {}

    def _emit(self, etype: int, code: int, value: int) -> None:
        if self._last.get((etype, code)) != value:
            self._last[(etype, code)] = value
            self.dev.write(etype, code, value)

    def send(self, state: ControllerState) -> None:
        b = state.buttons
        for name, code in self.buttons.items():
            self._emit(e.EV_KEY, code, int(name in b))
        ax = state.axes
        # evdev sticks are +y = down
        self._emit(e.EV_ABS, e.ABS_X, int(ax["left_x"] * STICK))
        self._emit(e.EV_ABS, e.ABS_Y, int(-ax["left_y"] * STICK))
        self._emit(e.EV_ABS, e.ABS_RX, int(ax["right_x"] * STICK))
        self._emit(e.EV_ABS, e.ABS_RY, int(-ax["right_y"] * STICK))
        self._emit(e.EV_ABS, e.ABS_Z, int(ax["lt"] * 255))
        self._emit(e.EV_ABS, e.ABS_RZ, int(ax["rt"] * 255))
        self._emit(e.EV_ABS, e.ABS_HAT0X, ("DPAD_RIGHT" in b) - ("DPAD_LEFT" in b))
        self._emit(e.EV_ABS, e.ABS_HAT0Y, ("DPAD_DOWN" in b) - ("DPAD_UP" in b))
        self.dev.syn()

    def close(self) -> None:
        self.send(ControllerState())
        self.dev.close()
