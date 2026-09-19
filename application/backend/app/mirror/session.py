"""One controller's connection: tracked hand -> calibration -> filter -> engage -> /hand/command."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Literal, Protocol, Sequence

import numpy as np

from ..config import Settings
from .calibration import Calibration
from .curl import bends
from .engage import Engage
from .one_euro import OneEuro

CAPTURE_S = 0.5
MAX_MESSAGE_CHARS = 128
POSES = ("open", "fist")

Pose = Literal["open", "fist"]


@dataclass(frozen=True)
class Hand:
    world: np.ndarray  # (21, 3) metres, hand-centred
    image: list[list[float]]  # 21 x [x, y] in 0..1, for the drawing


class Tracker(Protocol):
    def detect(self, jpeg: bytes) -> Hand | None: ...
    def close(self) -> None: ...


def parse_calibrate(text: str) -> Pose | None:
    """{"type": "calibrate", "pose": "open"|"fist"} -> the pose; None for anything else."""
    if len(text) > MAX_MESSAGE_CHARS:
        return None
    try:
        message = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(message, dict) or message.get("type") != "calibrate":
        return None
    pose = message.get("pose")
    return pose if pose in POSES else None


class MirrorSession:
    def __init__(
        self,
        settings: Settings,
        read_state: Callable[[], Sequence[float]],
        publish: Callable[[list[float]], None],
    ) -> None:
        self._read_state = read_state
        self._publish = publish
        self._command_tolerance = settings.mirror_command_tolerance
        self._engage = Engage()
        self._filter = OneEuro(settings.mirror_min_cutoff, settings.mirror_beta)
        self._poses: dict[str, np.ndarray] = {}
        self._calibration: Calibration | None = None
        self._capture: tuple[Pose, float, list[np.ndarray]] | None = None
        self._error: str | None = None
        self._published: list[float] | None = None

    def calibrate(self, pose: Pose, now: float) -> None:
        """Average the bends of the next CAPTURE_S as this pose. The hand holds until both are new."""
        self._capture = (pose, now + CAPTURE_S, [])
        self._calibration = None
        self._error = None
        self._engage.stop()

    def on_hand(self, hand: Hand | None, now: float) -> dict:
        """One processed frame -> the status message of /ws/mirror."""
        measured = None if hand is None else bends(hand.world)
        if measured is not None and not np.all(np.isfinite(measured)):
            measured = None
        if self._capture is not None:
            self._run_capture(measured, now)

        curls: list[float] | None = None
        if measured is None:
            self._filter.reset()
        elif self._calibration is not None:
            curls = [round(float(c), 4) for c in self._filter(self._calibration.curls(measured), now)]

        mode = self._engage.update(curls)
        command = self._engage.command
        if mode == "following" and command is not None and self._changed(command):
            self._publish(command)
            self._published = command
        return {
            "mode": mode,
            "calibrated": self._calibration is not None,
            "capturing": None if self._capture is None else self._capture[0],
            "error": self._error,
            "controller": curls,
            "command": command,
            "landmarks": None if hand is None else hand.image,
        }

    def _changed(self, command: list[float]) -> bool:
        if self._published is None:
            return True
        return any(abs(a - b) > self._command_tolerance for a, b in zip(command, self._published))

    def _run_capture(self, measured: np.ndarray | None, now: float) -> None:
        assert self._capture is not None
        pose, until, samples = self._capture
        if measured is not None:
            samples.append(measured)
        if now < until:
            return
        self._capture = None
        if not samples:
            self._error = "no_hand"
            return
        self._poses[pose] = np.mean(samples, axis=0)
        if len(self._poses) < len(POSES):
            return
        try:
            self._calibration = Calibration(open=self._poses["open"], fist=self._poses["fist"])
        except ValueError:
            self._error = "range"
            self._poses.clear()
            return
        self._poses.clear()
        self._filter.reset()
        self._engage.start(self._read_state())
