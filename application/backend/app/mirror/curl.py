"""21 hand landmarks -> how far each finger is bent, in radians."""

from __future__ import annotations

from typing import Sequence

import numpy as np

# Wrist, then the four landmarks of the finger: thumb 1..4, index 5..8, .. pinky 17..20.
CHAINS = tuple((0, *range(1 + 4 * finger, 5 + 4 * finger)) for finger in range(5))


def finger_bend(points: np.ndarray, chain: Sequence[int]) -> float:
    """Sum of the angles between successive bones: no dependence on position, size or rotation."""
    bones = np.diff(points[list(chain)], axis=0)
    unit = bones / np.linalg.norm(bones, axis=1, keepdims=True)
    cosines = np.clip(np.sum(unit[:-1] * unit[1:], axis=1), -1.0, 1.0)
    return float(np.arccos(cosines).sum())


def bends(points: np.ndarray) -> np.ndarray:
    """World landmarks (21, 3) -> 5 bends in finger order. Image landmarks will not do: a finger
    that curls towards the camera moves mostly in depth."""
    return np.array([finger_bend(points, chain) for chain in CHAINS])
