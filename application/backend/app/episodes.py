"""Record episodes from the console and play them back. The console's own format, one folder per episode:

    <recordings>/<dataset>/meta.json                  {"fps": 30, "task": "..."}
    <recordings>/<dataset>/episode_000/frames.jsonl   one line per tick: {"t", "state", "action", "camera1", "camera2"}
    <recordings>/<dataset>/episode_000/camera1/000000.jpg ...

`state` is /hand/state, `action` is the last /hand/command (the state until somebody commands):
the same two columns as `lerobot-record` with `exo_hand_command` writes. `camera1` is the head
camera (iPhone), `camera2` the wrist RealSense - the image keys of the policy - each the file of
the newest frame at that tick, or null while that camera is silent. A JPEG is written once, when
it is new. `policy/lerobot_robot_exo_hand/from_console.py` turns a dataset into a LeRobot one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Callable

from .hub import Hub

LOGGER = logging.getLogger(__name__)

FPS = 30
CAMERAS = {"camera1": "iphone", "camera2": "realsense"}  # policy image key -> the hub's camera source
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class EpisodeError(ValueError):
    """Something the page asked for that cannot be done; the text goes back to it."""


def episode_dirs(dataset: Path) -> list[Path]:
    return sorted(p for p in dataset.glob("episode_*") if (p / "frames.jsonl").is_file())


def read_frames(episode: Path) -> list[dict]:
    with open(episode / "frames.jsonl") as f:
        return [json.loads(line) for line in f if line.strip()]


class Episodes:
    """One recording or one replay at a time. Event-loop thread only."""

    def __init__(self, root: Path, hub: Hub, send_command: Callable[[list[float]], None]) -> None:
        self._root = root
        self._hub = hub
        self._send_command = send_command
        self._task: asyncio.Task | None = None
        self._status: dict = {"mode": "idle"}
        self._keep = True

    def status(self) -> dict:
        return dict(self._status)

    def datasets(self) -> list[dict]:
        found = []
        for dataset in sorted(p for p in self._root.glob("*") if (p / "meta.json").is_file()):
            meta = json.loads((dataset / "meta.json").read_text())
            episodes = [sum(1 for _ in open(e / "frames.jsonl")) for e in episode_dirs(dataset)]
            found.append({"name": dataset.name, "task": meta.get("task", ""), "fps": meta.get("fps", FPS), "episodes": episodes})
        return found

    def _dataset(self, name: str) -> Path:
        if not NAME.fullmatch(name):
            raise EpisodeError("a dataset name is letters, digits, - and _")
        return self._root / name

    def _busy(self) -> None:
        if self._task is not None and not self._task.done():
            raise EpisodeError(f"{self._status['mode']} is running: stop it first")

    # --- recording ---

    def start_recording(self, name: str, task: str) -> None:
        self._busy()
        dataset = self._dataset(name)
        dataset.mkdir(parents=True, exist_ok=True)
        meta = dataset / "meta.json"
        if not meta.is_file():
            meta.write_text(json.dumps({"fps": FPS, "task": task}))
        # after the highest number, not the count: a person may have deleted a bad episode
        index = max((int(p.name.split("_")[1]) + 1 for p in episode_dirs(dataset)), default=0)
        episode = dataset / f"episode_{index:03d}"
        if episode.exists():
            shutil.rmtree(episode)  # the leftover of a discarded or crashed recording
        for camera in CAMERAS:
            (episode / camera).mkdir(parents=True)
        self._keep = True
        self._status = {"mode": "recording", "dataset": name, "episode": index, "frame": 0, "frames": None}
        self._task = asyncio.create_task(self._record(episode))

    async def _record(self, episode: Path) -> None:
        versions = {camera: 0 for camera in CAMERAS}
        files: dict[str, str | None] = {camera: None for camera in CAMERAS}
        start = time.monotonic()
        try:
            with open(episode / "frames.jsonl", "w") as lines:
                while True:
                    tick = self._status["frame"]
                    await asyncio.sleep(max(0.0, start + tick / FPS - time.monotonic()))
                    for camera, source in CAMERAS.items():
                        channel = self._hub.frames[source]["color"]
                        if channel.latest is not None and channel.version != versions[camera]:
                            versions[camera] = channel.version
                            files[camera] = f"{camera}/{tick:06d}.jpg"
                            (episode / files[camera]).write_bytes(channel.latest.data)
                    state = self._hub.hand_state
                    lines.write(json.dumps({"t": round(tick / FPS, 4), "state": state,
                                            "action": self._hub.hand_command or state, **files}) + "\n")
                    self._status["frame"] = tick + 1
        finally:
            if not self._keep or self._status["frame"] == 0:
                shutil.rmtree(episode, ignore_errors=True)

    # --- replay ---

    def start_replay(self, name: str, index: int, what: str = "action", speed: float = 1.0) -> None:
        self._busy()
        if what not in ("action", "state") or not 0.1 <= speed <= 4.0:
            raise EpisodeError("what is action or state, speed is 0.1 .. 4")
        dataset = self._dataset(name)
        episodes = episode_dirs(dataset)
        if not 0 <= index < len(episodes):
            raise EpisodeError(f"{name} has no episode {index}")
        frames = read_frames(episodes[index])
        fps = json.loads((dataset / "meta.json").read_text()).get("fps", FPS)
        self._status = {"mode": "replaying", "dataset": name, "episode": index, "frame": 0, "frames": len(frames)}
        self._task = asyncio.create_task(self._replay(episodes[index], frames, fps * speed, what))

    async def _replay(self, episode: Path, frames: list[dict], rate: float, what: str) -> None:
        shown: dict[str, str | None] = {camera: None for camera in CAMERAS}
        start = time.monotonic()
        self._hub.replaying = True  # the live cameras stay off the panels meanwhile
        try:
            for tick, frame in enumerate(frames):
                await asyncio.sleep(max(0.0, start + tick / rate - time.monotonic()))
                self._send_command([float(v) for v in frame[what]])
                for camera, source in CAMERAS.items():
                    name = frame.get(camera)
                    if name and name != shown[camera]:
                        shown[camera] = name
                        jpeg = await asyncio.to_thread((episode / name).read_bytes)
                        self._hub.show_recorded(source, jpeg)
                self._status["frame"] = tick + 1
        finally:
            self._hub.replaying = False
            self._status = {"mode": "idle"}

    async def stop(self, keep: bool = True) -> None:
        """End the recording (keep=False throws the episode away) or the replay."""
        task, self._task = self._task, None
        self._keep = keep
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._status = {"mode": "idle"}
