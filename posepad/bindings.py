"""Bindings turn gesture states into virtual controller input."""

from __future__ import annotations

from dataclasses import dataclass, field

from .gestures import GestureState

BUTTONS = (
    "A", "B", "X", "Y", "LB", "RB", "BACK", "START", "GUIDE", "LS", "RS",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
)
BUTTON_ALIASES = {
    "SELECT": "BACK", "VIEW": "BACK", "MENU": "START", "HOME": "GUIDE",
    "L1": "LB", "R1": "RB", "L3": "LS", "R3": "RS",
    "UP": "DPAD_UP", "DOWN": "DPAD_DOWN", "LEFT": "DPAD_LEFT", "RIGHT": "DPAD_RIGHT",
    "CROSS": "A", "CIRCLE": "B", "SQUARE": "X", "TRIANGLE": "Y",
}
AXES = ("left_x", "left_y", "right_x", "right_y", "lt", "rt")
AXIS_ALIASES = {
    "lx": "left_x", "ly": "left_y", "rx": "right_x", "ry": "right_y",
    "left_trigger": "lt", "right_trigger": "rt", "l2": "lt", "r2": "rt",
}
TRIGGERS = ("lt", "rt")
MODES = ("hold", "tap", "toggle")


@dataclass
class ControllerState:
    """Everything the output backends need for one frame.

    Stick axes are -1..1 with +y = up; triggers are 0..1.
    """

    buttons: set[str] = field(default_factory=set)
    axes: dict[str, float] = field(default_factory=lambda: dict.fromkeys(AXES, 0.0))
    keys: set[str] = field(default_factory=set)

    def is_neutral(self) -> bool:
        return not self.buttons and not self.keys and not any(self.axes.values())


@dataclass
class Binding:
    gesture: str
    button: str | None = None
    axis: str | None = None
    key: str | None = None
    mode: str = "hold"
    tap_time: float = 0.08
    value: float | None = None       # axis value while a boolean gesture is active
    scale: float = 1.0
    deadzone: float = 0.0
    invert: bool = False

    # runtime
    _was_active: bool = field(default=False, init=False)
    _toggled: bool = field(default=False, init=False)
    _tap_until: float = field(default=-1.0, init=False)

    @property
    def target(self) -> str:
        if self.button:
            return f"button {self.button}"
        if self.axis:
            return f"axis {self.axis}"
        return f"key {self.key}"

    def reset(self) -> None:
        self._was_active = False
        self._toggled = False
        self._tap_until = -1.0

    def _digital(self, active: bool, now: float) -> bool:
        rising = active and not self._was_active
        self._was_active = active
        if self.mode == "toggle":
            if rising:
                self._toggled = not self._toggled
            return self._toggled
        if self.mode == "tap":
            if rising:
                self._tap_until = now + self.tap_time
            return now < self._tap_until
        return active

    def apply(self, st: GestureState, analog: bool, out: ControllerState, now: float) -> None:
        on = self._digital(st.active, now)
        if self.button:
            if on:
                out.buttons.add(self.button)
        elif self.key:
            if on:
                out.keys.add(self.key)
        elif self.axis:
            if analog and self.value is None and self.mode == "hold":
                v = st.value if st.tracked else 0.0
                if abs(v) < self.deadzone:
                    v = 0.0
            else:
                v = (1.0 if self.value is None else self.value) if on else 0.0
            v *= self.scale
            if self.invert:
                v = -v
            out.axes[self.axis] += v


class BindingSet:
    def __init__(self, bindings: list[Binding], analog: dict[str, bool]):
        self.bindings = bindings
        self.analog = analog

    def reset(self) -> None:
        for b in self.bindings:
            b.reset()

    def update(self, states: dict[str, GestureState], now: float) -> ControllerState:
        out = ControllerState()
        for b in self.bindings:
            b.apply(states[b.gesture], self.analog.get(b.gesture, False), out, now)
        for a in AXES:
            lo = 0.0 if a in TRIGGERS else -1.0
            out.axes[a] = max(lo, min(1.0, out.axes[a]))
        return out
