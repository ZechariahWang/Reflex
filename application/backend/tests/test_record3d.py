import asyncio
import socket
import threading
import time

import cv2
import numpy as np
import pytest
import uvicorn

from app.depth import Colorizer
from app.record3d import Record3DClient, encode_hue_depth, hue_depth_mm, normalize_host, render, render_rgbd
from tests.fake_record3d import create_phone


def test_hue_roundtrip_and_holes():
    depth = np.array([[0, 150, 600], [1500, 2400, 2999]], dtype=np.uint16)
    decoded = hue_depth_mm(encode_hue_depth(depth))
    assert decoded[0, 0] == 0
    assert np.abs(decoded.astype(int) - depth.astype(int)).max() <= 6  # 8-bit colour quantization


def test_grey_pixels_are_no_reading():
    grey = np.full((4, 4, 3), 128, dtype=np.uint8)
    assert not hue_depth_mm(grey).any()


def test_render_splits_depth_left_rgb_right():
    depth = np.full((120, 160), 400, dtype=np.uint16)
    rgb = np.zeros((120, 160, 3), dtype=np.uint8)
    rgb[..., 2] = 250  # pure red, BGR
    color, colorized = render(np.hstack((encode_hue_depth(depth), rgb)), Colorizer(150, 2000))
    assert (color.width, color.height) == (160, 120) == (colorized.width, colorized.height)
    shown = cv2.imdecode(np.frombuffer(color.data, np.uint8), cv2.IMREAD_COLOR)
    assert shown[..., 2].mean() > 200 and shown[..., 0].mean() < 40
    near = cv2.imdecode(np.frombuffer(colorized.data, np.uint8), cv2.IMREAD_COLOR)[60, 80]
    assert int(near[2]) > int(near[0])  # 0.4 m is near: warm, more red than blue


@pytest.mark.parametrize(
    ("text", "host"),
    [("192.168.1.23", "192.168.1.23"), (" http://my-iphone.local:8080/ ", "my-iphone.local:8080"),
     ("192.168.1.23/getOffer?x", None), ("a b", None), ("", None)],
)
def test_normalize_host(text, host):
    assert normalize_host(text) == host


@pytest.fixture
def phone_address():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_phone(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_streams_from_a_record3d_phone_over_webrtc(phone_address):
    async def scenario():
        frames = []
        client = Record3DClient(frames.append, phone_address)
        client.start()
        try:
            for _ in range(150):
                if len(frames) >= 5:
                    break
                await asyncio.sleep(0.1)
            return client.status(), [f.to_ndarray(format="bgr24") for f in frames[-1:]]
        finally:
            await client.stop()

    status, images = asyncio.run(scenario())
    assert status["state"] == "streaming", status
    image = images[0]
    assert image.shape[1] == 2 * 640 and image.shape[0] == 480
    depth = hue_depth_mm(image[:, :640])
    # The mock scene's floor runs from 2.1 m (top) to 0.6 m (bottom); video compression adds noise.
    top, bottom = np.median(depth[5:25, 5:60]), np.median(depth[-25:-5, 5:60])
    assert 1900 < top < 2200 and 550 < bottom < 800, (top, bottom)


def test_unreachable_phone_reports_error_and_keeps_retrying():
    async def scenario():
        client = Record3DClient(lambda frame: None, "127.0.0.1:9")
        client.start()
        await asyncio.sleep(1.0)
        status = client.status()
        await client.stop()
        return status, client.status()

    failing, stopped = asyncio.run(scenario())
    assert failing["state"] in ("error", "connecting") and failing["host"] == "127.0.0.1:9"
    assert stopped["state"] == "off"


class FakeUsbStream:
    """The slice of record3d.Record3DStream the client uses; frames come from a thread."""

    def __init__(self, devices=("iphone",), accepts=True, frames=True):
        self._devices, self._accepts, self._frames = list(devices), accepts, frames
        self.on_new_frame = self.on_stream_stopped = lambda: None
        self._running = threading.Event()
        self.disconnected = False

    def get_connected_devices(self):
        return self._devices

    def connect(self, device):
        if self._accepts and self._frames:
            self._running.set()
            threading.Thread(target=self._pump, daemon=True).start()
        return self._accepts

    def _pump(self):
        while self._running.is_set():
            self.on_new_frame()
            time.sleep(0.03)

    def get_rgb_frame(self):
        rgb = np.zeros((960, 720, 3), dtype=np.uint8)
        rgb[..., 0] = 250  # red, RGB order
        return rgb

    def get_depth_frame(self):
        depth = np.full((256, 192), 0.4, dtype=np.float32)
        depth[:20] = np.nan  # no reading
        return depth

    def disconnect(self):
        self._running.clear()
        self.disconnected = True


def run_usb(stream, seconds=0.6):
    async def scenario():
        frames = []
        client = Record3DClient(frames.append, "usb", usb_stream=lambda: stream)
        client.start()
        await asyncio.sleep(seconds)
        status = client.status()
        await client.stop()
        return status, frames

    return asyncio.run(scenario())


def test_usb_streams_rgb_and_metric_depth():
    stream = FakeUsbStream()
    status, frames = run_usb(stream)
    assert status["state"] == "streaming" and len(frames) > 3 and stream.disconnected
    color, colorized = render_rgbd(frames[-1], Colorizer(150, 2000))
    assert (color.width, color.height) == (720, 960) == (colorized.width, colorized.height)
    shown = cv2.imdecode(np.frombuffer(color.data, np.uint8), cv2.IMREAD_COLOR)
    assert shown[..., 2].mean() > 200 and shown[..., 0].mean() < 40  # still red after RGB -> BGR
    depth = cv2.imdecode(np.frombuffer(colorized.data, np.uint8), cv2.IMREAD_COLOR)
    assert abs(int(depth[5, 5, 0]) - 0xF6) < 6 and int(depth[500, 300, 2]) > int(depth[500, 300, 0])


@pytest.mark.parametrize(
    ("stream", "expected"),
    [(FakeUsbStream(devices=()), "no iPhone on USB"), (FakeUsbStream(accepts=False), "not streaming")],
)
def test_usb_problems_are_explained(stream, expected):
    status, frames = run_usb(stream, 0.3)
    assert status["state"] == "error" and expected in status["detail"] and not frames


def test_usb_is_a_valid_address():
    assert normalize_host(" USB ") == "usb"


def test_a_wedged_usbmuxd_is_reported_not_waited_for(monkeypatch):
    monkeypatch.setattr("app.record3d.USB_CALL_TIMEOUT_S", 0.2)
    release = threading.Event()

    class Wedged(FakeUsbStream):
        def get_connected_devices(self):
            release.wait(5)
            return []

    started = time.monotonic()
    status, frames = run_usb(Wedged(), 0.6)
    release.set()
    assert status["state"] == "error" and "usbmuxd is not answering" in status["detail"]
    assert time.monotonic() - started < 3 and not frames
