"""One controller's open hand and fist turn bends into curls, 0 = open .. 1 = closed."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MIN_RANGE_RAD = 0.3  # less than this between open and fist: the capture is wrong, and noise would fill 0..1


@dataclass(frozen=True)
class Calibration:
    open: np.ndarray
    fist: np.ndarray

    def __post_init__(self) -> None:
        if not np.all(self.fist - self.open >= MIN_RANGE_RAD):  # a NaN fails too
            raise ValueError("a finger bends too little between the open hand and the fist")

    def curls(self, bends: np.ndarray) -> np.ndarray:
        return np.clip((bends - self.open) / (self.fist - self.open), 0.0, 1.0)
