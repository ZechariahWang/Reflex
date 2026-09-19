"""Latest-value cache shared by the data source (ROS or mock) and the API.

`on_*` methods are safe to call from any thread (roslibpy calls back on the
Twisted reactor thread); everything else runs on the asyncio event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
import time
from collections import deque
from typing import AsyncIterator, Protocol, Sequence

import numpy as np
from av import VideoFrame

from . import record3d
from .config import Settings
from .depth import Colorizer
from .frames import Frame, LatestChannel, jpeg_size

LOGGER = logging.getLogger(__name__)

FINGERS = ("thumb", "index", "middle", "ring", "pinky")
TOPICS = ("joint_states", "hand_state", "hand_command", "color", "depth", "iphone")
CAMERA_SOURCES = ("realsense", "iphone")
CAMERA_KINDS = ("color", "depth")
RATE_WINDOW_S = 2.0
STALE_AFTER_MS = 2000
MAX_COMMAND_CHARS = 512  # a valid command is under 150


class Source(Protocol):
    """Where the data comes from: rosbridge or the mock generator."""

    @property
    def connected(self) -> bool: ...
    def start(self) -> None: ...
    async def stop(self) -> None: ...
    def send_command(self, values: list[float]) -> None: ...
    def set_passive(self, passive: bool) -> None: ...


def is_finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def finger_vector(values: Sequence[object]) -> list[float] | None:
    """Five finite numbers in finger order, or None for anything else ROS might send."""
    if len(values) != len(FINGERS) or not all(is_finite_number(value) for value in values):
        return None
    return [float(value) for value in values]


class RateMeter:
    def __init__(self) -> None:
        self._stamps: deque[float] = deque()
        self._last: float | None = None

    def tick(self, now: float) -> None:
        self._last = now
        self._stamps.append(now)
        self._prune(now)

    def hz(self, now: float) -> float:
        """Mean rate between the first and last message inside the window."""
        self._prune(now)
        if len(self._stamps) < 2:
            return 0.0
        return round((len(self._stamps) - 1) / (self._stamps[-1] - self._stamps[0]), 1)

    def age_ms(self, now: float) -> int | None:
        return None if self._last is None else int((now - self._last) * 1000)

    def _prune(self, now: float) -> None:
        while self._stamps and now - self._stamps[0] > RATE_WINDOW_S:
            self._stamps.popleft()


def parse_command(text: str) -> list[float] | None:
    """Validate a client message; returns 5 clamped values or None to ignore it."""
    if len(text) > MAX_COMMAND_CHARS:
        return None
    try:
        message = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(message, dict) or message.get("type") != "command":
        return None
    data = message.get("data")
    if not isinstance(data, list) or len(data) != len(FINGERS):
        return None
    values: list[float] = []
    for item in data:
        if not is_finite_number(item):
            return None
        values.append(min(1.0, max(0.0, float(item))))
    return values


def parse_passive(text: str) -> bool | None:
    """{"type": "passive", "data": true|false} -> the flag; None for anything else."""
    if len(text) > MAX_COMMAND_CHARS:
        return None
    try:
        message = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(message, dict) or message.get("type") != "passive":
        return None
    return message["data"] if isinstance(message.get("data"), bool) else None


async def ticks(period: float) -> AsyncIterator[None]:
    """Yield on a fixed, drift-free cadence; skips ahead instead of bursting when late."""
    loop = asyncio.get_running_loop()
    deadline = loop.time()
    while True:
        yield
        deadline = max(deadline + period, loop.time() - period)
        await asyncio.sleep(max(0.0, deadline - loop.time()))


class Hub:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._meters = {topic: RateMeter() for topic in TOPICS}
        self._joints: dict[str, float] = {f"{finger}_joint": 0.0 for finger in FINGERS}
        self._state: list[float] = [0.0] * len(FINGERS)
        self._command: list[float] | None = None
        self._passive = False
        self._urdf: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._colorizer = Colorizer(settings.depth_min_mm, settings.depth_max_mm)
        self._depth_payloads: LatestChannel[bytes] = LatestChannel()
        self.iphone_rotation = settings.record3d_rotation
        self._iphone_frames: LatestChannel[VideoFrame | np.ndarray | record3d.RgbdFrame] = LatestChannel()
        self.frames: dict[str, dict[str, LatestChannel[Frame]]] = {
            source: {kind: LatestChannel() for kind in CAMERA_KINDS} for source in CAMERA_SOURCES
        }

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # -- inputs, any thread -------------------------------------------------

    def on_joint_states(self, names: Sequence[str], positions: Sequence[object]) -> None:
        """Only the finger joints, only finite values; sim-only joints never reach the API."""
        with self._lock:
            self._meters["joint_states"].tick(time.monotonic())
            for name, position in zip(names, positions):
                if name in self._joints and is_finite_number(position):
                    self._joints[name] = float(position)

    def on_hand_state(self, values: Sequence[object]) -> None:
        vector = finger_vector(values)
        with self._lock:
            self._meters["hand_state"].tick(time.monotonic())
            if vector is not None:
                self._state = vector

    def on_hand_command(self, values: Sequence[object]) -> None:
        vector = finger_vector(values)
        with self._lock:
            self._meters["hand_command"].tick(time.monotonic())
            if vector is not None:
                self._command = vector

    def on_passive(self, passive: object) -> None:
        with self._lock:
            self._passive = passive is True

    def clear_hand_command(self) -> None:
        """Back to "nobody has commanded": the mock calls this when its override expires."""
        with self._lock:
            self._command = None

    def on_urdf(self, xml: str) -> None:
        with self._lock:
            self._urdf = xml

    def on_color(self, jpeg: bytes) -> None:
        self._tick("color")
        width, height = jpeg_size(jpeg)
        self._to_loop(self.frames["realsense"]["color"].publish, Frame(jpeg, width, height))

    def on_depth(self, payload: bytes) -> None:
        self._tick("depth")
        self._to_loop(self._depth_payloads.publish, payload)

    def on_iphone_frame(self, frame: VideoFrame | np.ndarray | record3d.RgbdFrame) -> None:
        """One Record3D frame, still undecoded: Wi-Fi (depth | RGB side by side) or USB (RGB + metres)."""
        self._tick("iphone")
        self._to_loop(self._iphone_frames.publish, frame)

    def _tick(self, topic: str) -> None:
        with self._lock:
            self._meters[topic].tick(time.monotonic())

    def _to_loop(self, fn, *args) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(fn, *args)

    # -- event loop ---------------------------------------------------------

    async def run_depth_worker(self) -> None:
        """Colorize the newest depth payload in a worker thread; stale ones are skipped."""
        seen = 0
        while True:
            seen, payload = await self._depth_payloads.next(seen)
            if self.frames["realsense"]["depth"].viewers == 0:
                continue  # nobody is looking at RealSense depth: skip the decode + colorize + encode
            try:
                frame = await asyncio.to_thread(self._colorizer.render, payload)
            except ValueError as error:
                LOGGER.warning("dropping depth frame: %s", error)
                continue
            except Exception:  # no single frame may end the loop
                LOGGER.exception("dropping depth frame")
                continue
            self.frames["realsense"]["depth"].publish(frame)

    def _render_iphone(
        self, frame: VideoFrame | np.ndarray | record3d.RgbdFrame, want: tuple[bool, bool]
    ) -> tuple[Frame | None, Frame | None]:
        if isinstance(frame, record3d.RgbdFrame):
            return record3d.render_rgbd(frame, self._colorizer, self.iphone_rotation, want)
        bgr = frame if isinstance(frame, np.ndarray) else frame.to_ndarray(format="bgr24")
        return record3d.render(bgr, self._colorizer, self.iphone_rotation, want)

    async def run_iphone_worker(self) -> None:
        """Split, decode and re-encode the newest iPhone frame in a worker thread."""
        seen = 0
        while True:
            seen, raw = await self._iphone_frames.next(seen)
            channels = self.frames["iphone"]
            want = (channels["color"].viewers > 0, channels["depth"].viewers > 0)
            if not any(want):
                continue
            try:
                color, depth = await asyncio.to_thread(self._render_iphone, raw, want)
            except Exception:  # no single frame may end the loop
                LOGGER.exception("dropping iPhone frame")
                continue
            if color is not None:
                channels["color"].publish(color)
            if depth is not None:
                channels["depth"].publish(depth)

    @property
    def hand_state(self) -> list[float]:
        with self._lock:
            return list(self._state)

    @property
    def urdf(self) -> str | None:
        with self._lock:
            return self._urdf

    def snapshot(self, ros_connected: bool) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                "t": round(time.time(), 3),
                "ros_connected": ros_connected,
                "fingers": list(FINGERS),
                "joints": dict(self._joints),
                "state": list(self._state),
                "command": None if self._command is None else list(self._command),
                "passive": self._passive,
                "rates": {topic: meter.hz(now) for topic, meter in self._meters.items()},
            }

    def health(self, ros_connected: bool) -> dict:
        now = time.monotonic()
        with self._lock:
            topics = {t: {"hz": m.hz(now), "age_ms": m.age_ms(now)} for t, m in self._meters.items()}
        return {
            "ros_connected": ros_connected,
            "mock": self._settings.mock,
            "rosbridge_url": self._settings.rosbridge_url,
            "topics": topics,
        }

    def camera_meta(self, source: str, kind: str) -> dict:
        meter = kind if source == "realsense" else source
        now = time.monotonic()
        with self._lock:
            hz = self._meters[meter].hz(now)
            age_ms = self._meters[meter].age_ms(now)
        frame = self.frames[source][kind].latest
        meta = {
            "type": "meta",
            "width": frame.width if frame else 0,
            "height": frame.height if frame else 0,
            "hz": round(hz * 2) / 2,  # half-hertz steps keep jitter from re-sending meta
            "available": age_ms is not None and age_ms < STALE_AFTER_MS,
        }
        if kind == "depth":
            meta["min_mm"] = self._settings.depth_min_mm
            meta["max_mm"] = self._settings.depth_max_mm
        return meta
