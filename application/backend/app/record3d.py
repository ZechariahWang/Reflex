"""iPhone depth camera through the Record3D app. Two transports, one client.

USB (address "usb"): the official `record3d` library over the cable (usbmuxd). No
network involved, so it works on isolating Wi-Fi such as eduroam, and depth
arrives as real float32 metres.

Wi-Fi (address = the IP the app shows): the app runs a small HTTP server on the
phone and streams one WebRTC video track. Phone and backend must be clients of
the same non-isolating network; the app does not serve while the phone is the
hotspot.

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
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
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
USB = "usb"
USB_CALL_TIMEOUT_S = 8.0
USB_STUCK = (
    "usbmuxd is not answering: replug the iPhone while it is unlocked; if that does not help, "
    "run: sudo systemctl restart usbmuxd"
)
MAX_SIDE_PX = 640  # the panel is ~450 px wide; bigger frames only cost the browser decode time
MAX_FPS = 30.0  # the phone sends 60; the page cannot show more and pays for every frame
ROTATIONS = {0: None, 90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
HOST_PATTERN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(:\d{1,5})?$")


@dataclass(frozen=True)
class RgbdFrame:
    """One USB frame: RGB picture and depth in metres (usually at a lower resolution)."""

    rgb: np.ndarray
    depth_m: np.ndarray


def normalize_host(text: str) -> str | None:
    """'http://192.168.1.7/' -> '192.168.1.7', 'USB' -> 'usb'; None if it is not a plain host[:port]."""
    if text.strip().lower() == USB:
        return USB
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


def _fit(image: np.ndarray, rotation: int, interpolation: int) -> np.ndarray:
    """Shrink to MAX_SIDE_PX, then turn. The sensor is portrait; 90 / 270 make it landscape."""
    scale = MAX_SIDE_PX / max(image.shape[:2])
    if scale < 1.0:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=interpolation)
    turn = ROTATIONS[rotation]
    return image if turn is None else cv2.rotate(image, turn)


def render(
    side_by_side_bgr: np.ndarray, colorizer: Colorizer, rotation: int = 0, want: tuple[bool, bool] = (True, True)
) -> tuple[Frame | None, Frame | None]:
    """One Wi-Fi frame -> (color JPEG, colorized depth JPEG); `want` skips the one nobody watches."""
    half = side_by_side_bgr.shape[1] // 2
    if half == 0:
        raise ValueError("Record3D frame has no width")
    color = depth = None
    if want[0]:
        color = _jpeg(_fit(side_by_side_bgr[:, half : half * 2], rotation, cv2.INTER_AREA))
    if want[1]:
        mm = _fit(hue_depth_mm(side_by_side_bgr[:, :half]), rotation, cv2.INTER_NEAREST)
        depth = _jpeg(colorizer.colorize(mm))
    return color, depth


def render_rgbd(
    frame: RgbdFrame, colorizer: Colorizer, rotation: int = 0, want: tuple[bool, bool] = (True, True)
) -> tuple[Frame | None, Frame | None]:
    """One USB frame -> (color JPEG, colorized depth JPEG), both at the (shrunk) colour image's shape."""
    bgr = _fit(frame.rgb, rotation, cv2.INTER_AREA)  # still RGB order; shrink before converting
    color = depth = None
    if want[0]:
        color = _jpeg(cv2.cvtColor(bgr, cv2.COLOR_RGB2BGR))
    if want[1]:
        mm = np.nan_to_num(frame.depth_m.astype(np.float32) * 1000.0, nan=0.0, posinf=0.0, neginf=0.0)
        mm = np.clip(mm, 0.0, 65535.0).round().astype(np.uint16)
        turn = ROTATIONS[rotation]
        mm = mm if turn is None else cv2.rotate(mm, turn)
        # Nearest keeps holes as holes instead of smearing 0 into the neighbouring depths.
        mm = cv2.resize(mm, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
        depth = _jpeg(colorizer.colorize(mm))
    return color, depth


def _usb_stream():
    """A fresh record3d stream object; imported lazily so Wi-Fi-only setups need not have it."""
    from record3d import Record3DStream

    return Record3DStream()


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

    def __init__(
        self,
        on_frame: Callable[[VideoFrame | RgbdFrame], None],
        host: str = "",
        usb_stream: Callable[[], object] = _usb_stream,
    ) -> None:
        self._on_frame = on_frame
        self._usb_stream = usb_stream
        self._host = host
        self._task: asyncio.Task[None] | None = None
        self._usb_stuck = False
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
                await (self._usb_session() if self._host == USB else self._session())
                problem = "stream ended"
            except ConnectionError as error:  # raised below with a ready-made explanation
                problem = str(error)
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
            accepted = 0.0
            while True:
                frame = await asyncio.wait_for(track.recv(), timeout)
                self.state, self.detail, timeout = "streaming", "", FRAME_TIMEOUT_S
                now = asyncio.get_running_loop().time()
                if now - accepted >= 0.9 / MAX_FPS:
                    accepted = now
                    self._on_frame(frame)
        except MediaStreamError:
            return
        finally:
            await peer.close()

    async def _usb_call(self, fn: Callable, *args: object):
        """Run a record3d call with a deadline. The library blocks for good when usbmuxd
        wedges, so it gets a daemon thread of its own (never the shared pool, never one
        that would hold up shutdown), and no second call is made while one is still stuck."""
        if self._usb_stuck:
            raise ConnectionError(USB_STUCK)
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        def settle(result: object, error: BaseException | None) -> None:
            if future.done():
                return
            if error is None:
                future.set_result(result)
            else:
                future.set_exception(error)

        def work() -> None:
            try:
                result, error = fn(*args), None
            except Exception as caught:  # handed to the awaiting coroutine
                result, error = None, caught
            self._usb_stuck = False  # it came back after all
            loop.call_soon_threadsafe(settle, result, error)

        threading.Thread(target=work, name="record3d-usb", daemon=True).start()
        try:
            return await asyncio.wait_for(future, USB_CALL_TIMEOUT_S)
        except asyncio.TimeoutError:
            self._usb_stuck = True
            raise ConnectionError(USB_STUCK) from None

    async def _usb_session(self) -> None:
        loop = asyncio.get_running_loop()
        stream = self._usb_stream()
        devices = await self._usb_call(stream.get_connected_devices)
        if not devices:
            raise ConnectionError("no iPhone on USB: plug it in, unlock it and tap Trust")
        stopped = asyncio.Event()
        last_frame = [0.0]

        def deliver(frame: RgbdFrame) -> None:
            last_frame[0] = loop.time()
            self.state, self.detail = "streaming", ""
            self._on_frame(frame)

        accepted = [0.0]

        def on_new_frame() -> None:  # record3d's own thread; its buffers are reused, so copy
            now = loop.time()
            if now - accepted[0] < 0.9 / MAX_FPS:
                return  # over the cap: dropped before the copy, which is the expensive part
            accepted[0] = now
            frame = RgbdFrame(np.array(stream.get_rgb_frame()), np.array(stream.get_depth_frame()))
            loop.call_soon_threadsafe(deliver, frame)

        stream.on_new_frame = on_new_frame
        stream.on_stream_stopped = lambda: loop.call_soon_threadsafe(stopped.set)
        try:
            if await self._usb_call(stream.connect, devices[0]) is False:
                raise ConnectionError(
                    "iPhone found, but Record3D is not streaming: Settings > Live RGBD Video "
                    "Streaming > USB, then press the red button"
                )
            started = loop.time()
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), 1.0)
                except asyncio.TimeoutError:
                    pass
                quiet = loop.time() - (last_frame[0] or started)
                if quiet > (FRAME_TIMEOUT_S if last_frame[0] else FIRST_FRAME_TIMEOUT_S):
                    raise ConnectionError("iPhone connected over USB, but no frames: press the red button in Record3D")
        finally:
            stream.on_new_frame = lambda: None
            try:
                await self._usb_call(stream.disconnect)
            except ConnectionError:
                pass  # already reported; nothing more to release
