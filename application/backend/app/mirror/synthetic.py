"""A hand made of straight bones: the mock tracker's hand, and known input for the tests."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

JOINT_MAX_RAD = 1.2
FAN_RAD = (0.9, 0.3, 0.0, -0.3, -0.6)  # thumb .. pinky, from the middle finger's direction
KNUCKLE_M = (0.03, 0.09, 0.09, 0.085, 0.08)
BONE_M = 0.03
INTO_PALM = np.array([0.0, 0.0, -1.0])


def hand(curls: Sequence[float]) -> np.ndarray:
    """21 world landmarks (metres, wrist at the origin); every joint of a finger bends curl * JOINT_MAX_RAD."""
    points = np.zeros((21, 3))
    for finger, curl in enumerate(curls):
        along = np.array([math.sin(FAN_RAD[finger]), math.cos(FAN_RAD[finger]), 0.0])
        point = KNUCKLE_M[finger] * along
        points[1 + 4 * finger] = point
        for joint in range(1, 4):
            angle = joint * curl * JOINT_MAX_RAD
            point = point + BONE_M * (math.cos(angle) * along + math.sin(angle) * INTO_PALM)
            points[1 + 4 * finger + joint] = point
    return points


def image_points(points: np.ndarray) -> list[list[float]]:
    """The same hand as MediaPipe's image landmarks: x, y in 0..1, y down."""
    return [[round(0.5 + 2.5 * x, 4), round(0.85 - 2.5 * y, 4)] for x, y, _ in points]
