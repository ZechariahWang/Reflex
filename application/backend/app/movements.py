"""Pre-written movements: the Python files of the repo's `movements/` folder (its README has the
format), listed for the page and played on /hand/command. Event-loop thread only."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import math
from pathlib import Path
from typing import Callable

LOGGER = logging.getLogger(__name__)

MAX_STEPS = 2000
MAX_STEP_S = 30.0
FINGER_COUNT = 5

Step = tuple[list[float], float]


class MovementError(ValueError):
    """Something the page asked for that cannot be done; the text goes back to it."""


def load(path: Path) -> dict:
    """One movement file -> {"name", "title", "description", "steps"}; MovementError says what is wrong with it."""
    spec = importlib.util.spec_from_file_location(f"movement_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # read again on every call: an edited file needs no restart
        raw = list(module.steps())
    except Exception as error:
        raise MovementError(f"{path.name}: {type(error).__name__}: {error}") from error
    if not 0 < len(raw) <= MAX_STEPS:
        raise MovementError(f"{path.name}: steps() gave {len(raw)} steps, it must be 1 .. {MAX_STEPS}")
    steps: list[Step] = []
    for number, step in enumerate(raw):
        try:
            pose, seconds = step
            values = [min(1.0, max(0.0, float(v))) for v in pose]
            seconds = float(seconds)
        except (TypeError, ValueError) as error:
            raise MovementError(f"{path.name}: step {number} is not (pose, seconds)") from error
        if len(values) != FINGER_COUNT or not all(map(math.isfinite, values)) or not 0.0 < seconds <= MAX_STEP_S:
            raise MovementError(f"{path.name}: step {number} needs {FINGER_COUNT} values and 0 < seconds <= {MAX_STEP_S:g}")
        steps.append((values, seconds))
    return {
        "name": path.stem,
        "title": str(getattr(module, "TITLE", path.stem)),
        "description": str(getattr(module, "DESCRIPTION", "")),
        "steps": steps,
    }


class Movements:
    def __init__(self, folder: Path, send_command: Callable[[list[float]], None]) -> None:
        self._folder = folder
        self._send_command = send_command
        self._task: asyncio.Task | None = None
        self._status: dict | None = None

    def status(self) -> dict | None:
        return None if self._status is None else dict(self._status)

    @property
    def playing(self) -> bool:
        return self._task is not None and not self._task.done()

    def _files(self) -> list[Path]:
        return sorted(p for p in self._folder.glob("*.py") if not p.name.startswith("_"))

    def listing(self) -> list[dict]:
        """What the dropdown shows. A broken file is listed with its error instead of vanishing."""
        found = []
        for path in self._files():
            try:
                movement = load(path)
                seconds = round(sum(s for _, s in movement["steps"]), 1)
                found.append({**{k: movement[k] for k in ("name", "title", "description")}, "seconds": seconds, "error": None})
            except MovementError as error:
                found.append({"name": path.stem, "title": path.stem, "description": "", "seconds": 0.0, "error": str(error)})
        return found

    def play(self, name: str) -> None:
        if self.playing:
            raise MovementError("a movement is playing: stop it first")
        path = next((p for p in self._files() if p.stem == name), None)
        if path is None:
            raise MovementError(f"no movement called {name}")
        movement = load(path)
        self._status = {"name": name, "title": movement["title"], "step": 0, "steps": len(movement["steps"])}
        self._task = asyncio.create_task(self._run(movement["steps"]))

    async def _run(self, steps: list[Step]) -> None:
        try:
            for number, (pose, seconds) in enumerate(steps, start=1):
                self._send_command(pose)
                self._status["step"] = number
                await asyncio.sleep(seconds)
        finally:
            self._status = None

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._status = None
