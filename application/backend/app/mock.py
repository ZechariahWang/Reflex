"""Synthetic data source for MOCK=1: no ROS, same Hub inputs as the real client."""

from __future__ import annotations

import asyncio
import math
import time

import cv2
import numpy as np

from .config import MOCK_URDF_PATH
from .depth import HEADER_BYTES
from .hub import FINGERS, Hub, ticks
from .record3d import encode_hue_depth

JOINT_MAX_RAD = 1.57
JOINT_RATE_HZ = 100
CAMERA_RATE_HZ = 15
CURL_PERIOD_S = 4.0
SLEW_PER_S = 2.5
COMMAND_HOLD_S = 3.0
WIDTH, HEIGHT = 640, 480
INK = (0x24, 0x24, 0x24)
PAPER = (0xF6, 0xF6, 0xF6)
HAIRLINE = (0xDC, 0xDC, 0xDC)
TRACK_ALPHA = 0.25
# The mock phone watches the same scene a few seconds later, so the two panels differ.
PHONE_TIME_OFFSET_S = 3.0


def encode_compressed_depth(depth_mm: np.ndarray) -> bytes:
    """Pack a uint16 millimetre image the way compressed_depth_image_transport does."""
    ok, png = cv2.imencode(".png", depth_mm, (cv2.IMWRITE_PNG_COMPRESSION, 1))
    if not ok:
        raise ValueError("PNG encode failed")
    return bytes(HEADER_BYTES) + png.tobytes()


class Scene:
    """A ball orbiting over a receding floor, rendered as aligned color and depth images."""

    def __init__(self) -> None:
        self._x, self._y = np.meshgrid(np.arange(WIDTH, dtype=np.float32), np.arange(HEIGHT, dtype=np.float32))
        self._floor = (2100.0 - 1500.0 * self._y / HEIGHT).astype(np.float32)
        self._backdrop = np.full((HEIGHT, WIDTH, 3), PAPER, dtype=np.uint8)
        self._backdrop[::40, :] = HAIRLINE
        self._backdrop[:, ::40] = HAIRLINE

    @staticmethod
    def _ball(t: float) -> tuple[float, float, float]:
        """Centre (px) and radius (px) at time t."""
        return (
            WIDTH / 2 + 190.0 * math.cos(t * 0.7),
            HEIGHT / 2 + 90.0 * math.sin(t * 1.1),
            70.0 + 22.0 * math.sin(t * 0.5),
        )

    def color_bgr(self, t: float) -> np.ndarray:
        cx, cy, radius = self._ball(t)
        centre = (round(cx), round(cy))
        tracked = self._backdrop.copy()
        cv2.line(tracked, (centre[0], 0), (centre[0], HEIGHT), INK, 1)
        cv2.line(tracked, (0, centre[1]), (WIDTH, centre[1]), INK, 1)
        image = cv2.addWeighted(tracked, TRACK_ALPHA, self._backdrop, 1.0 - TRACK_ALPHA, 0.0)
        cv2.circle(image, centre, round(radius), INK, -1, cv2.LINE_AA)
        return image

    def color_jpeg(self, t: float) -> bytes:
        ok, jpeg = cv2.imencode(".jpg", self.color_bgr(t), (cv2.IMWRITE_JPEG_QUALITY, 85))
        if not ok:
            raise ValueError("JPEG encode failed")
        return jpeg.tobytes()

    def depth_mm(self, t: float) -> np.ndarray:
        cx, cy, radius = self._ball(t)
        dx, dy = self._x - cx, self._y - cy
        inside = dx * dx + dy * dy
        bulge = np.sqrt(np.clip(radius * radius - inside, 0.0, None))
        near = 300.0 + 6.0 * (110.0 - radius)
        depth = np.where(inside < radius * radius, near + 1.2 * (radius - bulge), self._floor)
        # Stereo occlusion shadow: a sliver with no reading along the ball's left edge.
        shadow = (np.abs(dy) < radius) & (dx < 0) & (inside >= radius * radius) & (inside < (radius + 14.0) ** 2)
        depth[shadow] = 0.0
        return depth.astype(np.uint16)

    def depth_payload(self, t: float) -> bytes:
        return encode_compressed_depth(self.depth_mm(t))

    def record3d_frame(self, t: float) -> np.ndarray:
        """What the Record3D app streams: hue-encoded depth on the left, RGB on the right."""
        return np.hstack((encode_hue_depth(self.depth_mm(t)), self.color_bgr(t)))


class MockSource:
    connected = True

    def __init__(self, hub: Hub) -> None:
        self._hub = hub
        self._scene = Scene()
        self._tasks: list[asyncio.Task[None]] = []
        self._command = [0.0] * len(FINGERS)
        self._command_until = 0.0

    def start(self) -> None:
        self._hub.on_urdf(MOCK_URDF_PATH.read_text())
        self._hub.iphone_rotation = 0  # the mock phone is already landscape
        self._tasks = [asyncio.create_task(self._run_joints()), asyncio.create_task(self._run_camera())]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def send_command(self, values: list[float]) -> None:
        self._command = values
        self._command_until = time.monotonic() + COMMAND_HOLD_S
        self._hub.on_hand_command(values)

    async def _run_joints(self) -> None:
        state = [0.0] * len(FINGERS)
        max_step = SLEW_PER_S / JOINT_RATE_HZ
        names = [f"{finger}_joint" for finger in FINGERS]
        tick = 0
        async for _ in ticks(1 / JOINT_RATE_HZ):
            now = time.monotonic()
            if self._command_until and now >= self._command_until:
                self._command_until = 0.0
                self._hub.clear_hand_command()
            for i in range(len(FINGERS)):
                if now < self._command_until:
                    target = self._command[i]
                else:
                    target = 0.5 - 0.5 * math.cos(2 * math.pi * now / CURL_PERIOD_S - 0.9 * i)
                state[i] += min(max_step, max(-max_step, target - state[i]))
            self._hub.on_joint_states(names, [value * JOINT_MAX_RAD for value in state])
            if tick % 2 == 0:
                self._hub.on_hand_state(state)
            tick += 1

    async def _run_camera(self) -> None:
        async for _ in ticks(1 / CAMERA_RATE_HZ):
            t = time.monotonic()
            color, depth, phone = await asyncio.gather(
                asyncio.to_thread(self._scene.color_jpeg, t),
                asyncio.to_thread(self._scene.depth_payload, t),
                asyncio.to_thread(self._scene.record3d_frame, t + PHONE_TIME_OFFSET_S),
            )
            self._hub.on_color(color)
            self._hub.on_depth(depth)
            self._hub.on_iphone_frame(phone)
