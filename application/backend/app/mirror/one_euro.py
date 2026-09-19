"""One-euro filter (Casiez et al. 2012): heavy smoothing at rest, little lag in a fast move."""

from __future__ import annotations

import math

import numpy as np

DERIVATIVE_CUTOFF_HZ = 1.0


def _alpha(cutoff_hz: np.ndarray | float, dt: float) -> np.ndarray | float:
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / dt)


class OneEuro:
    def __init__(self, min_cutoff: float, beta: float) -> None:
        self._min_cutoff = min_cutoff
        self._beta = beta
        self.reset()

    def reset(self) -> None:
        self._t: float | None = None
        self._x = np.zeros(0)
        self._dx = np.zeros(0)

    def __call__(self, x: np.ndarray, t: float) -> np.ndarray:
        if self._t is None or t <= self._t:
            self._t, self._x, self._dx = t, x, np.zeros_like(x)
            return x
        dt = t - self._t
        rate = (x - self._x) / dt
        self._dx = self._dx + _alpha(DERIVATIVE_CUTOFF_HZ, dt) * (rate - self._dx)
        cutoff = self._min_cutoff + self._beta * np.abs(self._dx)
        self._x = self._x + _alpha(cutoff, dt) * (x - self._x)
        self._t = t
        return self._x
