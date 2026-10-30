"""Gesture definitions and the per-frame engine that evaluates them.

Four kinds of gesture, all configured from the profile:

``when``      a boolean expression - a static pose ("both hands up") or a
              movement using velocities ("right_wrist.vx > 8" is a punch)
``value``     a numeric expression - an analog control such as leaning to steer
``template``  a pose recorded with ``posepad record`` and matched by similarity
``sequence``  several steps that must happen in order within a time window
              (waves, flaps, "crouch then jump")

Each gesture produces a :class:`GestureState` every frame.  Debouncing
(``hold``), minimum on-time (``min_on``) and ``cooldown`` are shared by all of
them so quick motions register reliably without chattering.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .expr import Expression, ExpressionError, Missing
from .landmarks import ALL_POINTS, BodyFrame, Point
from .templates import PoseTemplate


@dataclass
class GestureState:
    active: bool = False
    value: float = 0.0          # 1/0 for boolean gestures, the number for analog ones
    since: float = 0.0          # timestamp of the last on/off transition
    tracked: bool = False       # False when the required body points were not visible

    def held_for(self, now: float) -> float:
        return now - self.since if self.active else 0.0


@dataclass
class Gesture:
    name: str
    hold: float = 0.0            # condition must be true this long before activating
    min_on: float = 0.0          # stay active at least this long once triggered
    cooldown: float = 0.0        # cannot re-trigger this soon after releasing
    threshold: float = 0.5       # analog gestures are "active" when |value| >= threshold
    min_visibility: float = 0.5
    analog: bool = field(default=False, init=False)

    # runtime
    state: GestureState = field(default_factory=GestureState, init=False)
    _pending_since: float | None = field(default=None, init=False)
    _released_at: float = field(default=-math.inf, init=False)

    def dependencies(self) -> set[str]:
        return set()

    def points(self) -> set[str]:
        return set()

    def raw(self, scope: Mapping[str, Any], frame: BodyFrame, now: float) -> tuple[bool, float]:
        raise NotImplementedError

    def reset(self) -> None:
        self.state = GestureState()
        self._pending_since = None
        self._released_at = -math.inf

    def step(self, scope: Mapping[str, Any], frame: BodyFrame | None, now: float) -> GestureState:
        tracked = frame is not None and all(
            frame.point(p).visibility >= self.min_visibility for p in self.points())
        want, value = False, 0.0
        if tracked:
            try:
                want, value = self.raw(scope, frame, now)
            except Missing:
                tracked = False
        st = self.state
        st.tracked = tracked
        st.value = value if tracked else 0.0

        if st.active:
            if not want and now - st.since >= self.min_on:
                st.active = False
                st.since = now
                self._released_at = now
            return st

        if not want:
            self._pending_since = None
            return st
        if now - self._released_at < self.cooldown:
            return st
        if self._pending_since is None:
            self._pending_since = now
        if now - self._pending_since >= self.hold:
            st.active = True
            st.since = now
            self._pending_since = None
        return st


@dataclass
class ExprGesture(Gesture):
    when: Expression | None = None
    release: Expression | None = None   # optional hysteresis: stay on until this is true
    value_expr: Expression | None = None

    def __post_init__(self) -> None:
        self.analog = self.value_expr is not None

    def _exprs(self) -> list[Expression]:
        return [e for e in (self.when, self.release, self.value_expr) if e is not None]

    def dependencies(self) -> set[str]:
        return set().union(*(e.names for e in self._exprs()))

    def points(self) -> set[str]:
        return set().union(*(e.points for e in self._exprs()))

    def raw(self, scope, frame, now):
        if self.value_expr is not None:
            v = float(self.value_expr.evaluate(scope))
            if not math.isfinite(v):
                raise Missing(self.name)
            on = abs(v) >= self.threshold
            if self.when is not None:
                on = bool(self.when.evaluate(scope))
            return on, v
        on = bool(self.when.evaluate(scope))
        if self.state.active and self.release is not None:
            on = not bool(self.release.evaluate(scope))
        return on, 1.0 if on else 0.0


@dataclass
class TemplateGesture(Gesture):
    template: PoseTemplate | None = None
    tolerance: float = 0.35

    def __post_init__(self) -> None:
        self.analog = False

    def points(self) -> set[str]:
        return set()  # handled per-joint in raw(): a few hidden joints are tolerated

    def raw(self, scope, frame, now):
        err = self.template.error(frame, self.min_visibility)
        if err is None:
            raise Missing(self.name)
        # similarity: 1 = exact match, 0.5 = at the tolerance edge, 0 = twice as far
        sim = max(0.0, 1.0 - err / (2.0 * self.tolerance))
        return err <= self.tolerance, sim


@dataclass
class SequenceGesture(Gesture):
    steps: list[Expression] = field(default_factory=list)
    within: float = 1.0          # seconds allowed from first to last step

    _index: int = field(default=0, init=False)
    _started: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self.analog = False
        if self.min_on == 0.0:
            self.min_on = 0.15   # completed sequences are momentary; make them visible

    def dependencies(self) -> set[str]:
        return set().union(*(e.names for e in self.steps))

    def points(self) -> set[str]:
        return set().union(*(e.points for e in self.steps))

    def reset(self) -> None:
        super().reset()
        self._index = 0

    @property
    def progress(self) -> int:
        return self._index

    def raw(self, scope, frame, now):
        if self._index > 0 and now - self._started > self.within:
            self._index = 0
        if not bool(self.steps[self._index].evaluate(scope)):
            # Seeing the first step again restarts the clock.
            if self._index > 0 and bool(self.steps[0].evaluate(scope)):
                self._index, self._started = 1, now
            return False, 0.0
        if self._index == 0:
            self._started = now
        self._index += 1
        if self._index == len(self.steps):
            self._index = 0
            return True, 1.0
        return False, 0.0


class GestureEngine:
    """Evaluates every gesture once per frame in dependency order."""

    def __init__(self, gestures: dict[str, Gesture]):
        self.gestures = gestures
        self.order = topological_order(gestures)
        self.frame: BodyFrame | None = None
        self.now = 0.0

    def reset(self) -> None:
        for g in self.gestures.values():
            g.reset()

    def update(self, frame: BodyFrame | None, now: float) -> dict[str, GestureState]:
        self.frame, self.now = frame, now
        scope = _FrameScope(self)
        for name in self.order:
            self.gestures[name].step(scope, frame, now)
        return {n: g.state for n, g in self.gestures.items()}

    def evaluate(self, expr: Expression) -> Any:
        """Evaluate an ad-hoc expression against the current frame (for ``--watch``)."""
        if self.frame is None:
            return None
        try:
            return expr.evaluate(_FrameScope(self))
        except (Missing, ExpressionError):
            return None


class _FrameScope(Mapping):
    def __init__(self, engine: GestureEngine):
        self.engine = engine
        self._points: dict[str, Point] = {}

    def __getitem__(self, key: str) -> Any:
        if key in self.engine.gestures:
            g = self.engine.gestures[key]
            return g.state.value if g.analog else g.state.active
        if self.engine.frame is not None and key in ALL_POINTS:
            if key not in self._points:
                self._points[key] = self.engine.frame.point(key)
            return self._points[key]
        raise Missing(key)

    def __iter__(self):
        return iter(self.engine.gestures)

    def __len__(self) -> int:
        return len(self.engine.gestures)


def topological_order(gestures: dict[str, Gesture]) -> list[str]:
    """Order gestures so that each is evaluated after those it references."""
    order: list[str] = []
    state: dict[str, int] = {}

    def visit(name: str, path: list[str]) -> None:
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            cycle = " -> ".join(path[path.index(name):] + [name])
            raise ExpressionError(f"gestures reference each other in a loop: {cycle}")
        state[name] = 1
        for dep in sorted(gestures[name].dependencies()):
            if dep in gestures:
                visit(dep, path + [name])
        state[name] = 2
        order.append(name)

    for n in gestures:
        visit(n, [])
    return order
