"""Signal smoothing for noisy landmark tracks."""

from __future__ import annotations

import math

import numpy as np


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    """Vectorised 1-euro filter (Casiez et al., 2012).

    Low ``min_cutoff`` removes jitter when still; higher ``beta`` reduces lag
    during fast moves.  ``derivative`` holds the filtered rate of change of the
    last update, which doubles as a cheap velocity estimate.
    """

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.05, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self) -> None:
        self._x: np.ndarray | None = None
        self._t: float | None = None
        self.derivative: np.ndarray | None = None

    def __call__(self, x: np.ndarray, t: float) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        if self._x is None or self._t is None or self._x.shape != x.shape:
            self._x, self._t = x.copy(), t
            self.derivative = np.zeros_like(x)
            return x.copy()
        dt = t - self._t
        if dt <= 0:
            return self._x.copy()
        dx = (x - self._x) / dt
        a_d = _alpha(self.d_cutoff, dt)
        self.derivative = a_d * dx + (1 - a_d) * self.derivative
        cutoff = self.min_cutoff + self.beta * np.abs(self.derivative)
        a = 1.0 / (1.0 + (1.0 / (2.0 * math.pi * cutoff)) / dt)
        self._x = a * x + (1 - a) * self._x
        self._t = t
        return self._x.copy()
