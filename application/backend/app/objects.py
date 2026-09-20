"""Objects around the hand: detections in the RealSense colour image, placed in 3-D with the
aligned depth image and tracked over time in the camera's own frame.

The camera is bolted to the hand, so a position in `camera_link` is a position relative to the
hand, and the viewer hangs the objects under that link: they sit around the hand wherever it is.
A track outlives its detections for MEMORY_S, so an object that leaves the view fades instead of
vanishing (it stays where it was last seen in the hand's frame; nothing here knows how the hand
moved since - that is the ego-motion question in docs/system-design.md).

Pure functions and the tracker have no OpenCV or model import; the detector is optional.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np

LOGGER = logging.getLogger(__name__)

# The colour box shrinks to its middle before the depth is read: the edges are background.
CORE_FRACTION = 0.5
# Fewer valid depth pixels than this under a box = no position (a hole, or too close for the D435)
MIN_DEPTH_SAMPLES = 24
# A detection within this of a track of the same label is that object again
GATE_M = 0.20
# Weight of a new measurement in a track's position and size
SMOOTHING = 0.35
# A track unseen for this long is forgotten. Short: an object that is not detected any more goes
# from the map at once; this is only the time the page needs to fade it out (world-layer.tsx: gone
# from SEEN_S to FADE_S), and it rides out a single missed pass of the detector.
MEMORY_S = 1.0
# Detections in a row before a track is reported: one-frame flicker never reaches the page
CONFIRM_HITS = 2
# What the detector looks for: names of the model's classes (COCO for yolov8n: "cup", "bowl",
# "cell phone", "remote", "scissors", ... - the full list is `YOLO(model).names`). Add to this
# list to see more; everything else is never reported, and the model is told to skip it.
DETECT_LABELS = [
    "bottle",
]


@dataclass(frozen=True)
class Intrinsics:
    """Pinhole model of the colour stream (the aligned depth shares it)."""

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    @classmethod
    def from_camera_info(cls, message: dict) -> Intrinsics:
        """A sensor_msgs/CameraInfo as rosbridge sends it (ROS 2 spells the matrix `k`)."""
        k = message.get("k") or message["K"]
        return cls(float(k[0]), float(k[4]), float(k[2]), float(k[5]), int(message["width"]), int(message["height"]))

    @classmethod
    def default(cls, width: int, height: int) -> Intrinsics:
        """A D435 colour stream, roughly: ~69 deg horizontal field of view. Used until camera_info arrives."""
        fx = width / (2.0 * math.tan(math.radians(69.0) / 2.0))
        return cls(fx, fx, width / 2.0, height / 2.0, width, height)


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    # x0, y0, x1, y1 in colour-image pixels
    box: tuple[float, float, float, float]


@dataclass(frozen=True)
class Located:
    """A detection with a place: metres in camera_link (x forward, y left, z up), size on the same axes."""

    label: str
    confidence: float
    xyz: tuple[float, float, float]
    size: tuple[float, float, float]


def locate(detection: Detection, depth_mm: np.ndarray, intrinsics: Intrinsics) -> Located | None:
    """Median depth under the middle of the box, projected through the pinhole into camera_link.

    The optical frame of the image (x right, y down, z forward) becomes the ROS camera_link
    frame (x forward, y left, z up) that the URDF places on the hand.
    """
    x0, y0, x1, y1 = detection.box
    rows, cols = depth_mm.shape[:2]
    # The aligned depth normally matches the colour image; scale the box if a profile differs.
    sx, sy = cols / intrinsics.width, rows / intrinsics.height
    inset = (1.0 - CORE_FRACTION) / 2.0
    cx0 = int((x0 + (x1 - x0) * inset) * sx)
    cx1 = int((x1 - (x1 - x0) * inset) * sx)
    cy0 = int((y0 + (y1 - y0) * inset) * sy)
    cy1 = int((y1 - (y1 - y0) * inset) * sy)
    core = depth_mm[max(0, cy0) : max(0, cy1 + 1), max(0, cx0) : max(0, cx1 + 1)]
    valid = core[core > 0]
    if valid.size < MIN_DEPTH_SAMPLES:
        return None
    z = float(np.median(valid)) / 1000.0
    u, v = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    right = (u - intrinsics.cx) * z / intrinsics.fx
    down = (v - intrinsics.cy) * z / intrinsics.fy
    width = (x1 - x0) * z / intrinsics.fx
    height = (y1 - y0) * z / intrinsics.fy
    # Depth extent is unknown from one view: assume the object is about as deep as its narrow side.
    return Located(detection.label, detection.confidence, (z, -right, -down), (min(width, height), width, height))


@dataclass
class Track:
    id: int
    label: str
    xyz: list[float]
    size: list[float]
    confidence: float
    first_seen: float
    last_seen: float
    hits: int = 1


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b)))


ROTATIONS = (0, 90, 180, 270)


def box_before_rotation(box: tuple[float, float, float, float], rotation: int, width: int, height: int):
    """A box found in a picture that was turned clockwise by `rotation` -> the same box in the
    picture as the camera sent it (`width` x `height`), where the depth and the intrinsics live."""
    x0, y0, x1, y1 = box
    if rotation == 90:
        return (y0, height - 1 - x1, y1, height - 1 - x0)
    if rotation == 180:
        return (width - 1 - x1, height - 1 - y1, width - 1 - x0, height - 1 - y0)
    if rotation == 270:
        return (width - 1 - y1, x0, width - 1 - y0, x1)
    return box


class Tracker:
    """Greedy nearest-neighbour association by label, exponential smoothing, and a memory."""

    def __init__(self, gate_m: float = GATE_M, memory_s: float = MEMORY_S) -> None:
        self._gate = gate_m
        self._memory = memory_s
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    def update(self, located: Sequence[Located], now: float) -> None:
        candidates = sorted(
            (_distance(track.xyz, item.xyz), track.id, i)
            for track in self._tracks.values()
            for i, item in enumerate(located)
            if track.label == item.label
        )
        matched_tracks: set[int] = set()
        matched_items: set[int] = set()
        for distance, track_id, i in candidates:
            if distance > self._gate or track_id in matched_tracks or i in matched_items:
                continue
            matched_tracks.add(track_id)
            matched_items.add(i)
            track, item = self._tracks[track_id], located[i]
            track.xyz = [p + (q - p) * SMOOTHING for p, q in zip(track.xyz, item.xyz)]
            track.size = [p + (q - p) * SMOOTHING for p, q in zip(track.size, item.size)]
            track.confidence = item.confidence
            track.last_seen = now
            track.hits += 1
        for i, item in enumerate(located):
            if i in matched_items:
                continue
            self._tracks[self._next_id] = Track(
                self._next_id, item.label, list(item.xyz), list(item.size), item.confidence, now, now
            )
            self._next_id += 1
        for track_id in [t.id for t in self._tracks.values() if now - t.last_seen > self._memory]:
            del self._tracks[track_id]

    def objects(self, now: float) -> list[dict]:
        """What the page sees: confirmed tracks, oldest first. `age` is seconds since the last sighting."""
        return [
            {
                "id": track.id,
                "label": track.label,
                "xyz": [round(v, 4) for v in track.xyz],
                "size": [round(v, 4) for v in track.size],
                "confidence": round(track.confidence, 3),
                "age": round(max(0.0, now - track.last_seen), 2),
                "hits": track.hits,
            }
            for track in sorted(self._tracks.values(), key=lambda t: t.id)
            if track.hits >= CONFIRM_HITS
        ]

    def clear(self) -> None:
        self._tracks.clear()


class Detector(Protocol):
    name: str

    def detect(self, bgr: np.ndarray) -> list[Detection]: ...


class YoloDetector:
    """Ultralytics YOLO on the CPU (or CUDA if torch finds one). `pip install -r requirements-detect.txt`."""

    def __init__(self, model: str, confidence: float = 0.35, image_size: int = 416, threads: int = 2) -> None:
        import torch
        from ultralytics import YOLO  # torch: only imported when a model is configured

        # Left alone, torch takes every core and the rest of the machine (sim, browser) starves
        torch.set_num_threads(max(1, threads))
        self.name = model
        self._model = YOLO(model)
        self._confidence = confidence
        self._image_size = image_size
        ids = {name: index for index, name in self._model.names.items()}
        unknown = [label for label in DETECT_LABELS if label not in ids]
        if unknown:
            LOGGER.warning("DETECT_LABELS has names that %s does not know: %s", model, unknown)
        self._classes = [ids[label] for label in DETECT_LABELS if label in ids]

    def detect(self, bgr: np.ndarray) -> list[Detection]:
        if not self._classes:
            return []
        result = self._model.predict(
            bgr, imgsz=self._image_size, conf=self._confidence, classes=self._classes, verbose=False
        )[0]
        names = result.names
        boxes = result.boxes
        detections = []
        for box, conf, cls in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()):
            label = str(names[int(cls)])
            detections.append(Detection(label, float(conf), (box[0], box[1], box[2], box[3])))
        return detections


def make_detector(model: str, threads: int = 2) -> Detector | None:
    """None (and one log line) when no model is configured or its library is not installed."""
    if not model:
        return None
    try:
        detector = YoloDetector(model, threads=threads)
    except ImportError:
        LOGGER.warning(
            "DETECT_MODEL=%s but ultralytics is not installed (pip install -r requirements-detect.txt): "
            "no objects will be tracked",
            model,
        )
        return None
    except Exception:  # a bad model name, no network for the weights, ...
        LOGGER.exception("could not load DETECT_MODEL=%s: no objects will be tracked", model)
        return None
    LOGGER.info("object detector %s ready", model)
    return detector


class MockObjects:
    """Synthetic surroundings, for the mock console and for a sim that has no camera: a table's
    worth of objects in front of the hand, drifting a little, one of which leaves the view for a
    few seconds of every cycle so the memory fade can be seen.

    Coordinates are camera_link as the RealSense is mounted on this hand (hand_params.yaml
    `camera.rpy`): x forward along the fingers, y the back of the hand (world up when it rests
    palm down), z towards the thumb. The camera sits portrait, so its "up" is the thumb side.
    """

    # label, camera_link position (m), size on the same axes (m); the table is ~12 cm below the camera
    ITEMS = (
        ("bottle", (0.42, -0.01, 0.12), (0.07, 0.22, 0.07)),
        ("cup", (0.34, -0.075, -0.15), (0.08, 0.09, 0.09)),
        ("cell phone", (0.56, -0.115, -0.04), (0.15, 0.01, 0.07)),
        ("keyboard", (0.72, -0.11, 0.18), (0.14, 0.02, 0.44)),
        ("apple", (0.29, -0.085, 0.02), (0.07, 0.07, 0.07)),
    )
    CYCLE_S = 20.0
    AWAY_S = 7.0

    def located(self, t: float) -> list[Located]:
        out = []
        for i, (label, (x, y, z), size) in enumerate(self.ITEMS):
            if label == "cup" and (t % self.CYCLE_S) > self.CYCLE_S - self.AWAY_S:
                continue
            drift_x = 0.015 * math.sin(0.5 * t + i)
            drift_z = 0.012 * math.cos(0.35 * t + 2 * i)
            confidence = 0.86 - 0.03 * i + 0.04 * math.sin(1.3 * t + i)
            out.append(Located(label, round(confidence, 3), (x + drift_x, y, z + drift_z), size))
        return out
