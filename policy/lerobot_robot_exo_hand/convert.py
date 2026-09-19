"""Conversions between the rosbridge messages and the LeRobot dicts. No lerobot or roslibpy import."""

import math
from collections.abc import Iterable, Mapping, Sequence

import cv2
import numpy as np

# Contract order of /hand/command and /hand/state
FINGERS = ("thumb", "index", "middle", "ring", "pinky")
KEYS = tuple(f"{finger}.pos" for finger in FINGERS)
# An image slot of smolvla_base. lerobot async inference has no rename_map, so the key must match the policy
CAMERA = "camera2"


def decode_color(jpeg: bytes) -> np.ndarray:
    """JPEG bytes -> H x W x 3 uint8 RGB."""
    bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("payload is not a decodable image")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def to_observation(state: Sequence[float], rgb: np.ndarray) -> dict[str, float | np.ndarray]:
    if len(state) != len(FINGERS):
        raise ValueError(f"state has {len(state)} values, expected {len(FINGERS)}")
    return {**{key: float(value) for key, value in zip(KEYS, state)}, CAMERA: rgb}


def to_command(action: Mapping[str, float]) -> list[float]:
    """Action dict -> 5 values in contract order, clamped to 0..1."""
    values = [float(action[key]) for key in KEYS]
    # min/max would turn a NaN into 0.0, which opens that finger
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"action has a non-finite value: {values}")
    return [min(1.0, max(0.0, value)) for value in values]


def differs(a: Sequence[float], b: Sequence[float], tolerance: float) -> bool:
    return any(abs(x - y) > tolerance for x, y in zip(a, b))


def is_fresh(stamps: Iterable[float | None], now: float, max_age_s: float) -> bool:
    """True if every arrival time exists and is at most max_age_s old."""
    return all(stamp is not None and now - stamp <= max_age_s for stamp in stamps)
