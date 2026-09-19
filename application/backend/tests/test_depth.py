import cv2
import numpy as np
import pytest

from app.depth import Colorizer, decode
from app.frames import jpeg_size
from app.mock import encode_compressed_depth


def synthetic() -> np.ndarray:
    depth = np.zeros((48, 64), dtype=np.uint16)
    depth[:, 16:32] = 150
    depth[:, 32:48] = 2000
    depth[:, 48:] = 60000
    return depth


def test_decode_round_trips_16_bit_values():
    assert np.array_equal(decode(encode_compressed_depth(synthetic())), synthetic())


def test_decode_rejects_8_bit_payload():
    ok, png = cv2.imencode(".png", np.zeros((4, 4), dtype=np.uint8))
    with pytest.raises(ValueError):
        decode(bytes(12) + png.tobytes())


def test_colorize_near_warm_far_cool_holes_light():
    bgr = Colorizer(150, 2000).colorize(synthetic())
    assert bgr.shape == (48, 64, 3) and bgr.dtype == np.uint8
    assert tuple(bgr[0, 0]) == (0xF6, 0xF6, 0xF6)
    near_b, _, near_r = bgr[0, 20]
    far_b, _, far_r = bgr[0, 40]
    assert near_r > near_b and far_b > far_r
    assert np.array_equal(bgr[0, 60], bgr[0, 40])


def test_render_produces_jpeg_with_size():
    frame = Colorizer(150, 2000).render(encode_compressed_depth(synthetic()))
    assert frame.data[:2] == b"\xff\xd8" and (frame.width, frame.height) == (64, 48)
    assert jpeg_size(frame.data) == (64, 48)
    hole = cv2.imdecode(np.frombuffer(frame.data, np.uint8), cv2.IMREAD_COLOR)[24, 6]
    assert all(abs(int(c) - 0xF6) <= 4 for c in hole)


@pytest.mark.parametrize("payload", [b"", bytes(12), bytes(12) + b"not a png"])
def test_decode_rejects_truncated_payloads(payload):
    with pytest.raises(ValueError):
        decode(payload)
