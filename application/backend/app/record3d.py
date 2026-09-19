"""iPhone depth camera through the Record3D app's Wi-Fi streaming.

The app runs a small HTTP server on the phone and streams one WebRTC video track:

    GET  http://<phone>/getOffer  -> {"type": "offer", "sdp": ...}
    POST http://<phone>/answer    <- {"type": "answer", "data": <our sdp, ICE gathered>}

Every video frame is two images side by side: the LEFT half is depth encoded as
colour (HSV hue, depth_m = 3 * hue), the RIGHT half is the RGB picture. The phone
serves a single viewer at a time, so this client is the only thing that talks to it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Callable

import cv2
import numpy as np
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame

from .depth import JPEG_QUALITY, Colorizer
from .frames import Frame

LOGGER = logging.getLogger(__name__)

HUE_RANGE_MM = 3000.0  # a full turn of hue
# Pixels too grey or too dark to carry a hue are "no reading": the encoder only
# ever emits fully saturated, fully bright colours.
MIN_SATURATION = 0.35
MIN_VALUE = 0.25
HTTP_TIMEOUT_S = 10.0  # the phone gathers its ICE candidates before it answers /getOffer
FIRST_FRAME_TIMEOUT_S = 10.0
FRAME_TIMEOUT_S = 3.0
RETRY_MIN_S, RETRY_MAX_S = 1.0, 8.0
HOST_PATTERN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(:\d{1,5})?$")


def normalize_host(text: str) -> str | None:
    """'http://192.168.1.7/' -> '192.168.1.7'; None if it is not a plain host[:port]."""
    host = text.strip().removeprefix("http://").removeprefix("https://").rstrip("/")
    return host if HOST_PATTERN.fullmatch(host) else None


def hue_depth_mm(encoded_bgr: np.ndarray) -> np.ndarray:
    """Depth half of a Record3D frame -> uint16 millimetres (0 = no reading)."""
    hsv = cv2.cvtColor(encoded_bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2HSV)
    depth = hsv[..., 0] * (HUE_RANGE_MM / 360.0)
    depth[(hsv[..., 1] < MIN_SATURATION) | (hsv[..., 2] < MIN_VALUE)] = 0.0
    return depth.round().astype(np.uint16)


def encode_hue_depth(depth_mm: np.ndarray) -> np.ndarray:
    """Inverse of hue_depth_mm, for the mock source and the tests."""
    hsv = np.empty((*depth_mm.shape, 3), dtype=np.float32)
    hsv[..., 0] = np.clip(depth_mm.astype(np.float32), 0.0, HUE_RANGE_MM - 1.0) * (360.0 / HUE_RANGE_MM)
    hsv[..., 1] = 1.0
    hsv[..., 2] = np.where(depth_mm > 0, 1.0, 0.0)
    return (cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR) * 255.0).round().astype(np.uint8)


def _jpeg(bgr: np.ndarray) -> Frame:
    ok, jpeg = cv2.imencode(".jpg", bgr, (cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY))
    if not ok:
        raise ValueError("JPEG encode failed")
    height, width = bgr.shape[:2]
    return Frame(jpeg.tobytes(), width, height)


def render(side_by_side_bgr: np.ndarray, colorizer: Colorizer) -> tuple[Frame, Frame]:
    """One Record3D frame -> (color JPEG, colorized depth JPEG)."""
    half = side_by_side_bgr.shape[1] // 2
    if half == 0:
        raise ValueError("Record3D frame has no width")
    depth = colorizer.colorize(hue_depth_mm(side_by_side_bgr[:, :half]))
    return _jpeg(side_by_side_bgr[:, half : half * 2]), _jpeg(depth)


def _http_json(url: str, body: dict | None = None) -> dict | None:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        text = response.read().decode() or "null"
    try:
        return json.loads(text)
    except ValueError:
        return None  # the phone answers POST /answer with a non-JSON body


class Record3DClient:
    """Keeps a WebRTC session to the phone alive; hands every decoded frame to `on_frame`.

    Runs entirely on the asyncio loop. States: off (no address), connecting,
    streaming, error (with `detail`; it keeps retrying).
    """

    def __init__(self, on_frame: Callable[[VideoFrame], None], host: str = "") -> None:
        self._on_frame = on_frame
        self._host = host
        self._task: asyncio.Task[None] | None = None
        self.state = "off"
        self.detail = ""

    @property
    def host(self) -> str:
        return self._host

    def status(self) -> dict:
        return {"host": self._host, "state": self.state, "detail": self.detail}

    def start(self) -> None:
        if self._host and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.state, self.detail = "off", ""

    async def set_host(self, host: str) -> None:
        """Point at another phone ('' = disconnect)."""
        await self.stop()
        self._host = host
        self.start()

    async def _run(self) -> None:
        delay = RETRY_MIN_S
        while True:
            self.state, self.detail = "connecting", ""
            try:
                await self._session()
                problem = "stream ended"
            except (urllib.error.URLError, OSError, asyncio.TimeoutError) as error:
                problem = f"cannot reach {self._host}: {getattr(error, 'reason', error) or 'timed out'}"
            except Exception as error:  # a bad SDP, a codec error...: report it and retry
                LOGGER.exception("Record3D session failed")
                problem = str(error) or type(error).__name__
            if self.state == "streaming":
                delay = RETRY_MIN_S  # it worked a moment ago: retry promptly
            self.state, self.detail = "error", problem
            LOGGER.info("Record3D %s: %s; retrying in %.0f s", self._host, problem, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX_S)

    async def _session(self) -> None:
        base = f"http://{self._host}"
        # Phone and backend share a LAN: host candidates only, no STUN round trip.
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        tracks: asyncio.Queue = asyncio.Queue()
        peer.on("track", lambda track: tracks.put_nowait(track) if track.kind == "video" else None)
        try:
            offer = await asyncio.to_thread(_http_json, f"{base}/getOffer")
            if not isinstance(offer, dict) or "sdp" not in offer:
                raise ValueError("the phone sent no WebRTC offer - is Record3D in Wi-Fi streaming mode?")
            await peer.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type=offer.get("type", "offer")))
            await peer.setLocalDescription(await peer.createAnswer())  # gathers ICE before returning
            await asyncio.to_thread(
                _http_json, f"{base}/answer", {"type": "answer", "data": peer.localDescription.sdp}
            )
            track = await asyncio.wait_for(tracks.get(), FIRST_FRAME_TIMEOUT_S)
            timeout = FIRST_FRAME_TIMEOUT_S
            while True:
                frame = await asyncio.wait_for(track.recv(), timeout)
                self.state, self.detail, timeout = "streaming", "", FRAME_TIMEOUT_S
                self._on_frame(frame)
        except MediaStreamError:
            return
        finally:
            await peer.close()
