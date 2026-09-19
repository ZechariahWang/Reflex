"""What the mirror sends: the controller's curls while a hand is seen, the last command while not."""

from __future__ import annotations

from typing import Literal, Sequence

Mode = Literal["off", "no_hand", "following"]


class Engage:
    def __init__(self) -> None:
        self.command: list[float] | None = None

    def start(self, state: Sequence[float]) -> None:
        """Hold the measured pose until the first hand is seen."""
        self.command = list(state)

    def stop(self) -> None:
        self.command = None

    def update(self, curls: Sequence[float] | None) -> Mode:
        """One processed frame (`curls` is None when no hand was seen); `command` is what to send."""
        if self.command is None:
            return "off"
        if curls is None:
            return "no_hand"
        self.command = list(curls)
        return "following"
