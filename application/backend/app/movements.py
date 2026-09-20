"""Pre-written movements: the Python files of the repo's `movements/` folder (its README has the
format), listed for the page and played on /hand/command. Event-loop thread only."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import math
import re
from pathlib import Path
from typing import Callable

LOGGER = logging.getLogger(__name__)

MAX_STEPS = 2000
MAX_STEP_S = 30.0
FINGER_COUNT = 5

Step = tuple[list[float], float]
NAME = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
# First line of a file that was written through the API (teach). Only such a file may be
# overwritten or deleted through it: a movement somebody wrote by hand is never touched.
TAUGHT = "# Taught through the console API (PUT /api/movements/<name>): a hard-coded path."


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
    steps = check(raw, path.name)
    return {
        "name": path.stem,
        "title": str(getattr(module, "TITLE", path.stem)),
        "description": str(getattr(module, "DESCRIPTION", "")),
        "steps": steps,
    }


def check(steps: list, where: str) -> list[Step]:
    """(pose, seconds) pairs as they come -> clean steps; MovementError says what is wrong."""
    if not 0 < len(steps) <= MAX_STEPS:
        raise MovementError(f"{where}: {len(steps)} steps, it must be 1 .. {MAX_STEPS}")
    out: list[Step] = []
    for number, step in enumerate(steps):
        try:
            pose, seconds = step
            values = [min(1.0, max(0.0, float(v))) for v in pose]
            seconds = float(seconds)
        except (TypeError, ValueError) as error:
            raise MovementError(f"{where}: step {number} is not (pose, seconds)") from error
        if len(values) != FINGER_COUNT or not all(map(math.isfinite, values)) or not 0.0 < seconds <= MAX_STEP_S:
            raise MovementError(f"{where}: step {number} needs {FINGER_COUNT} values and 0 < seconds <= {MAX_STEP_S:g}")
        out.append((values, seconds))
    return out


def source_of(title: str, description: str, steps: list[Step]) -> str:
    """The Python file of a taught movement: the path as a literal list, readable and editable by hand."""
    rows = "".join(f"    ({[round(v, 3) for v in pose]}, {round(seconds, 3)}),\n" for pose, seconds in steps)
    return (
        f"{TAUGHT}\n"
        f"# Pose order: thumb, index, middle, ring, pinky; 0 = open .. 1 = closed. (pose, seconds to wait after it)\n\n"
        f"TITLE = {title!r}\nDESCRIPTION = {description!r}\n\nSTEPS = [\n{rows}]\n\n\ndef steps():\n    return STEPS\n"
    )


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

    def read(self, name: str) -> dict:
        """One movement with its steps, e.g. to change it and teach it again."""
        path = self._path(name)
        if not path.is_file():
            raise MovementError(f"no movement called {name}")
        movement = load(path)
        return {**movement, "steps": [{"pose": pose, "seconds": seconds} for pose, seconds in movement["steps"]],
                "taught": self._taught(path)}

    def teach(self, name: str, title: str, description: str, steps: list) -> dict:
        """Write (or replace) a taught movement. A file somebody wrote by hand is refused."""
        path = self._path(name)
        if path.is_file() and not self._taught(path):
            raise MovementError(f"{name} was written by hand: it is not replaced through the API, choose another name")
        clean = check([(step["pose"], step["seconds"]) if isinstance(step, dict) else step for step in steps], name)
        self._folder.mkdir(parents=True, exist_ok=True)
        path.write_text(source_of(title or name, description, clean))
        return self.read(name)

    def forget(self, name: str) -> None:
        path = self._path(name)
        if not path.is_file():
            raise MovementError(f"no movement called {name}")
        if not self._taught(path):
            raise MovementError(f"{name} was written by hand: delete the file yourself")
        path.unlink()

    def _path(self, name: str) -> Path:
        if not NAME.fullmatch(name):
            raise MovementError("a movement name is lower case letters, digits and _, starting with a letter")
        return self._folder / f"{name}.py"

    @staticmethod
    def _taught(path: Path) -> bool:
        with open(path) as f:
            return f.readline().rstrip("\n") == TAUGHT

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._status = None
