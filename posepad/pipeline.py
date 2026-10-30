"""Camera-independent core: raw landmarks in, controller state out."""

from __future__ import annotations

from dataclasses import dataclass

from .bindings import BindingSet, ControllerState
from .config import Profile
from .gestures import GestureEngine, GestureState
from .landmarks import BodyFrame, RawPose
from .tracker import PoseTracker


@dataclass
class StepResult:
    frame: BodyFrame | None
    states: dict[str, GestureState]
    output: ControllerState


class Pipeline:
    def __init__(self, profile: Profile, aspect: float = 4 / 3):
        self.profile = profile
        self.aspect = aspect
        s = profile.smoothing
        self.tracker = PoseTracker(min_cutoff=float(s.get("min_cutoff", 1.5)),
                                   beta=float(s.get("beta", 0.3)),
                                   calibrate_after=float(s.get("calibrate_after", 1.0)))
        self.engine = GestureEngine(profile.gestures)
        self.bindings = BindingSet(profile.bindings,
                                   {n: g.analog for n, g in profile.gestures.items()})

    def swap_profile(self, profile: Profile) -> None:
        """Hot-reload: keep the tracker (and its calibration), replace the rest."""
        self.profile = profile
        self.engine = GestureEngine(profile.gestures)
        self.bindings = BindingSet(profile.bindings,
                                   {n: g.analog for n, g in profile.gestures.items()})

    def step(self, raw: RawPose | None, now: float) -> StepResult:
        frame = self.tracker.update(raw, now, self.aspect)
        states = self.engine.update(frame, now)
        out = self.bindings.update(states, now) if frame is not None else ControllerState()
        if frame is None:
            self.bindings.reset()
        return StepResult(frame, states, out)
