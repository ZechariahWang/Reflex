"""When the controller's hand may move the exoskeleton: only after it matched the held command."""

from __future__ import annotations

from typing import Literal, Sequence

Mode = Literal["off", "no_hand", "frozen", "following"]


class Engage:
    def __init__(self, match_tolerance: float, frame_timeout_s: float) -> None:
        self._match_tolerance = match_tolerance
        self._frame_timeout_s = frame_timeout_s
        self.command: list[float] | None = None
        self._following = False
        self._last_frame = 0.0

    def start(self, state: Sequence[float]) -> None:
        """Hold the measured pose: the controller matches the real hand before the first motion."""
        self.command = list(state)
        self._following = False

    def update(self, curls: Sequence[float] | None, now: float) -> Mode:
        """One processed frame (`curls` is None when no hand was seen); `command` is what to send."""
        if self.command is None:
            return "off"
        if now - self._last_frame > self._frame_timeout_s:
            self._following = False
        self._last_frame = now
        if curls is None:
            self._following = False
            return "no_hand"
        if not self._following:
            self._following = all(abs(c - h) <= self._match_tolerance for c, h in zip(curls, self.command))
        if not self._following:
            return "frozen"
        self.command = list(curls)
        return "following"
