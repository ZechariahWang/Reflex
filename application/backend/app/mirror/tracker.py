"""MediaPipe HandLandmarker: one JPEG frame -> the landmarks of one hand."""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from .session import Hand

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "hand_landmarker.task"


class MediaPipeTracker:
    def __init__(self) -> None:
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO,  # tracks between frames: steadier and faster than IMAGE
            num_hands=1,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._stamp_ms = 0

    def detect(self, jpeg: bytes) -> Hand | None:
        bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            return None
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        self._stamp_ms = max(self._stamp_ms + 1, int(time.monotonic() * 1000))  # must rise strictly
        result = self._landmarker.detect_for_video(image, self._stamp_ms)
        if not result.hand_world_landmarks:
            return None
        return Hand(
            world=np.array([[p.x, p.y, p.z] for p in result.hand_world_landmarks[0]]),
            image=[[round(p.x, 4), round(p.y, 4)] for p in result.hand_landmarks[0]],
        )

    def close(self) -> None:
        self._landmarker.close()
