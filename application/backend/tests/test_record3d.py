import asyncio
import functools
import multiprocessing
import socket
import threading
import time

import cv2
import numpy as np
import pytest
import uvicorn

from app.depth import Colorizer
from app.record3d import RgbdFrame, Record3DClient, encode_hue_depth, hue_depth_mm, normalize_host, render, render_rgbd
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
    """The slice of record3d.Record3DStream the worker uses; frames come from a thread.

    Module level (and built with functools.partial below) because it is created
    inside the spawned worker process, so it has to be picklable by reference.
    """

    def __init__(self, devices=("iphone",), accepts=True, wedged=False, frames_for_s=None, silent=False):
        self._devices, self._accepts, self._wedged, self._frames_for_s = list(devices), accepts, wedged, frames_for_s
        self._silent = silent  # connected, but the phone streams to someone else and never closes us
        self.on_new_frame = self.on_stream_stopped = lambda: None

    def get_connected_devices(self):
        if self._wedged:
            time.sleep(60)  # usbmuxd not answering
        return self._devices

    def connect(self, device):
        if self._accepts and not self._silent:
            threading.Thread(target=self._pump, daemon=True).start()
        return self._accepts

    def _pump(self):
        started = time.monotonic()
        while self._frames_for_s is None or time.monotonic() - started < self._frames_for_s:
            self.on_new_frame()
            time.sleep(1 / 60)  # the real phone sends 60 fps
        self.on_stream_stopped()  # the user pressed stop on the phone

    def get_rgb_frame(self):
        rgb = np.zeros((960, 720, 3), dtype=np.uint8)
        rgb[..., 0] = 250  # red, RGB order
        return rgb

    def get_depth_frame(self):
        depth = np.full((256, 192), 0.4, dtype=np.float32)
        depth[:20] = np.nan  # no reading
        return depth


def usb_workers():
    return [p for p in multiprocessing.active_children() if p.name == "record3d-usb"]


def run_usb(factory, seconds):
    async def scenario():
        frames = []
        client = Record3DClient(frames.append, "usb", usb_stream=factory)
        client.start()
        await asyncio.sleep(seconds)
        status = client.status()
        await client.stop()
        return status, frames

    return asyncio.run(scenario())


def test_usb_streams_rgb_and_metric_depth_then_really_disconnects():
    status, frames = run_usb(FakeUsbStream, 3.0)
    assert status["state"] == "streaming" and len(frames) > 10
    assert len(frames) <= 3.0 * 30 + 2  # the fake sends 60 fps; the 30 fps cap holds
    assert frames[-1].rgb.shape == (640, 480, 3)  # shrunk in the worker, before crossing the pipe
    # Killing the worker is the disconnect: record3d never closes its socket, so a live worker
    # would be a ghost connection that makes the phone refuse the next one.
    assert usb_workers() == []
    color, colorized = render_rgbd(frames[-1], Colorizer(150, 2000))
    assert (color.width, color.height) == (480, 640) == (colorized.width, colorized.height)
    shown = cv2.imdecode(np.frombuffer(color.data, np.uint8), cv2.IMREAD_COLOR)
    assert shown[..., 2].mean() > 200 and shown[..., 0].mean() < 40  # still red after RGB -> BGR
    depth = cv2.imdecode(np.frombuffer(colorized.data, np.uint8), cv2.IMREAD_COLOR)
    assert abs(int(depth[5, 5, 0]) - 0xF6) < 6 and int(depth[400, 300, 2]) > int(depth[400, 300, 0])


def test_rotation_makes_the_portrait_sensor_landscape():
    frame = FakeUsbStream()
    rgbd = RgbdFrame(frame.get_rgb_frame(), frame.get_depth_frame())
    color, depth = render_rgbd(rgbd, Colorizer(150, 2000), rotation=90)
    assert (color.width, color.height) == (640, 480) == (depth.width, depth.height)
    # The no-reading band sits along the sensor's top edge; turned clockwise it is the right edge.
    turned = cv2.imdecode(np.frombuffer(depth.data, np.uint8), cv2.IMREAD_COLOR)
    assert abs(int(turned[240, 636, 0]) - 0xF6) < 6 and abs(int(turned[240, 5, 0]) - 0xF6) > 20


def test_only_the_watched_image_is_rendered():
    frame = FakeUsbStream()
    rgbd = RgbdFrame(frame.get_rgb_frame(), frame.get_depth_frame())
    color, depth = render_rgbd(rgbd, Colorizer(150, 2000), want=(True, False))
    assert color is not None and depth is None


@pytest.mark.parametrize(
    ("factory", "expected"),
    [
        (functools.partial(FakeUsbStream, devices=()), "no iPhone on USB"),
        (functools.partial(FakeUsbStream, accepts=False), "not serving USB"),
        (functools.partial(FakeUsbStream, frames_for_s=0.0, silent=True), "sends no frames"),
    ],
)
def test_usb_problems_are_explained(factory, expected, monkeypatch):
    monkeypatch.setattr("app.record3d.USB_FIRST_FRAME_TIMEOUT_S", 0.5)
    status, frames = run_usb(factory, 2.5)
    # Mid-retry the state reads "connecting", but the explanation stays put.
    assert status["state"] in ("error", "connecting") and expected in status["detail"] and not frames
    assert usb_workers() == []


def test_stop_on_the_phone_then_start_again_reconnects_by_itself():
    """The reported bug: after the stream ended, only pressing the button on the phone helped."""
    status, frames = run_usb(functools.partial(FakeUsbStream, frames_for_s=1.0), 6.0)
    # 1 s of frames, stream stops, retry after 1 s, 1 s of frames again, ... : several sessions.
    assert len(frames) > 45, len(frames)
    assert usb_workers() == []


def test_a_wedged_usbmuxd_is_reported_and_the_worker_killed(monkeypatch):
    monkeypatch.setattr("app.record3d.USB_START_TIMEOUT_S", 2.0)
    status, frames = run_usb(functools.partial(FakeUsbStream, wedged=True), 3.0)
    assert status["state"] == "error" and "usbmuxd is not answering" in status["detail"] and not frames
    assert usb_workers() == []


def test_usb_is_a_valid_address():
    assert normalize_host(" USB ") == "usb"
