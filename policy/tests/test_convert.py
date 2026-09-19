import cv2
import numpy as np
import pytest

from lerobot_robot_exo_hand.convert import (
    FINGERS,
    decode_color,
    differs,
    is_fresh,
    to_command,
    to_observation,
)


def action(**overrides):
    return {f"{f}.pos": 0.5 for f in FINGERS} | overrides


def test_decode_color_returns_rgb():
    red_bgr = np.zeros((8, 8, 3), np.uint8)
    red_bgr[..., 2] = 255
    ok, jpeg = cv2.imencode(".jpg", red_bgr)
    assert ok

    rgb = decode_color(jpeg.tobytes())

    assert rgb.shape == (8, 8, 3) and rgb.dtype == np.uint8
    assert rgb[0, 0, 0] > 200 and rgb[0, 0, 2] < 50


def test_decode_color_rejects_garbage():
    with pytest.raises(ValueError):
        decode_color(b"not a jpeg")


def test_to_observation_keeps_finger_order():
    rgb = np.zeros((4, 4, 3), np.uint8)

    obs = to_observation([0.0, 0.1, 0.2, 0.3, 0.4], rgb)

    assert list(obs) == [f"{f}.pos" for f in FINGERS] + ["wrist"]
    assert obs["thumb.pos"] == 0.0 and obs["pinky.pos"] == 0.4
    assert obs["wrist"] is rgb


def test_to_observation_rejects_wrong_length():
    with pytest.raises(ValueError):
        to_observation([0.0] * 4, np.zeros((4, 4, 3), np.uint8))


def test_to_command_orders_and_clamps():
    # dict order differs from the contract order on purpose
    shuffled = dict(reversed(action(**{"thumb.pos": -0.2, "pinky.pos": 1.7, "index.pos": 0.25}).items()))

    assert to_command(shuffled) == [0.0, 0.25, 0.5, 0.5, 1.0]


def test_to_command_rejects_missing_finger():
    incomplete = action()
    del incomplete["ring.pos"]
    with pytest.raises(KeyError):
        to_command(incomplete)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_to_command_rejects_non_finite(bad):
    with pytest.raises(ValueError):
        to_command(action(**{"middle.pos": bad}))


def test_differs_uses_tolerance_per_finger():
    base = [0.5] * 5

    assert not differs(base, base, 0.01)
    assert not differs([0.5, 0.5, 0.505, 0.5, 0.5], base, 0.01)
    assert differs([0.5, 0.5, 0.52, 0.5, 0.5], base, 0.01)


def test_slow_drift_gets_published():
    """Steps below the tolerance add up, because the reference is the last published command."""
    published = [0.0] * 5
    sent = 0
    for step in range(1, 11):
        wanted = [step * 0.004] * 5
        if differs(wanted, published, 0.01):
            published, sent = wanted, sent + 1

    assert sent == 3
    assert published[0] == pytest.approx(0.036)


def test_is_fresh():
    assert is_fresh([9.9, 9.8], now=10.0, max_age_s=0.3)
    assert not is_fresh([9.9, 9.6], now=10.0, max_age_s=0.3)
    assert not is_fresh([9.9, None], now=10.0, max_age_s=0.3)
