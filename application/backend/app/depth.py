"""compressedDepth payload -> colorized JPEG.

The payload is a 12-byte header followed by a 16-bit grayscale PNG whose pixel
values are millimetres (0 = no reading).
"""

from __future__ import annotations

import cv2
import numpy as np

from .frames import Frame

# 640x480 work gains nothing from OpenCV's thread pool, which burns ~4x the CPU spinning.
cv2.setNumThreads(1)

HEADER_BYTES = 12
HOLE_BGR = (0xF6, 0xF6, 0xF6)
JPEG_QUALITY = 80


def decode(payload: bytes) -> np.ndarray:
    """Return the uint16 millimetre image inside a compressedDepth payload."""
    if len(payload) <= HEADER_BYTES:
        raise ValueError("compressedDepth payload too short")
    png = np.frombuffer(payload, dtype=np.uint8, offset=HEADER_BYTES)
    try:
        depth = cv2.imdecode(png, cv2.IMREAD_UNCHANGED)
    except cv2.error as error:
        raise ValueError(str(error)) from error
    if depth is None or depth.dtype != np.uint16 or depth.ndim != 2:
        raise ValueError("payload is not a 16-bit grayscale compressedDepth image")
    return depth


class Colorizer:
    """Maps millimetres to BGR in two table lookups: mm -> palette index -> colour.

    Near is warm and far is cool over [min_mm, max_mm]; 0 (no reading) becomes
    the light UI background so holes read as intentional on a white page.
    """

    # Far -> near. A quiet two-hue ramp: a full rainbow shouts on a monochrome page.
    # The frontend legend and depth probe mirror these stops (src/lib/depth-ramp.ts).
    RAMP_RGB = ((0x2F, 0x4A, 0x63), (0x7F, 0x9B, 0xB3), (0xD9, 0xDD, 0xE0), (0xE9, 0xC9, 0xA8), (0xC2, 0x41, 0x0C))

    def __init__(self, min_mm: int, max_mm: int) -> None:
        if max_mm <= min_mm:
            raise ValueError("DEPTH_MAX_MM must be greater than DEPTH_MIN_MM")
        mm = np.arange(65536, dtype=np.float32)
        nearness = 1.0 - np.clip((mm - min_mm) / (max_mm - min_mm), 0.0, 1.0)
        self._index = np.round(1.0 + nearness * 254.0).astype(np.uint8)
        self._index[0] = 0
        stops = np.array(self.RAMP_RGB, dtype=np.float32)[:, ::-1]
        at = np.linspace(0.0, len(stops) - 1.0, 256)
        channels = [np.interp(at, np.arange(len(stops)), stops[:, c]) for c in range(3)]
        self._palette = np.stack(channels, axis=1).round().astype(np.uint8).reshape(256, 1, 3)
        self._palette[0, 0] = HOLE_BGR

    def colorize(self, depth: np.ndarray) -> np.ndarray:
        return cv2.applyColorMap(np.take(self._index, depth), self._palette)

    def render(self, payload: bytes) -> Frame:
        bgr = self.colorize(decode(payload))
        ok, jpeg = cv2.imencode(".jpg", bgr, (cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY))
        if not ok:
            raise ValueError("JPEG encode failed")
        height, width = bgr.shape[:2]
        return Frame(jpeg.tobytes(), width, height)
