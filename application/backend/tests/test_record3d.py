import asyncio
import socket
import threading
import time

import cv2
import numpy as np
import pytest
import uvicorn

from app.depth import Colorizer
from app.record3d import Record3DClient, encode_hue_depth, hue_depth_mm, normalize_host, render
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
