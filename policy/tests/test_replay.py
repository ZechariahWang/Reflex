import cv2
import numpy as np
import pytest

from lerobot_robot_exo_hand.replay import play, to_jpeg


def decoded(jpeg):
    return cv2.cvtColor(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def test_to_jpeg_takes_a_dataset_image_channels_first_float_rgb():
    image = np.zeros((3, 48, 64), np.float32)
    image[0] = 1.0  # red

    out = decoded(to_jpeg(image))

    assert out.shape == (48, 64, 3)
    assert out[24, 32, 0] > 240 and out[24, 32, 1] < 15 and out[24, 32, 2] < 15


def test_to_jpeg_takes_a_uint8_image_channels_last_too():
    image = np.zeros((48, 64, 3), np.uint8)
    image[..., 2] = 255  # blue

    out = decoded(to_jpeg(image))

    assert out[24, 32, 2] > 240 and out[24, 32, 0] < 15


class Clock:
    def __init__(self):
        self.now = 100.0
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_play_sends_every_frame_at_its_time_command_first():
    clock, sent = Clock(), []
    frames = [([i / 10] * 5, {"camera2": bytes([i])}) for i in range(4)]

    count = play(frames, 10.0, lambda v: sent.append(("command", clock.now, v[0])),
                 lambda key, jpeg: sent.append((key, clock.now, jpeg[0])), clock=lambda: clock.now, sleep=clock.sleep)

    assert count == 4
    assert [(kind, round(t - 100.0, 3)) for kind, t, _ in sent] == [
        ("command", 0.0), ("camera2", 0.0), ("command", 0.1), ("camera2", 0.1),
        ("command", 0.2), ("camera2", 0.2), ("command", 0.3), ("camera2", 0.3),
    ]
    assert [value for kind, _, value in sent if kind == "command"] == [0.0, 0.1, 0.2, 0.3]


def test_play_at_half_speed_takes_twice_as_long_and_a_slow_send_does_not_add_up():
    clock = Clock()

    def slow_send(values):
        clock.now += 0.15  # each send takes longer than a frame at full speed

    play([([0.0] * 5, {})] * 5, 10.0, slow_send, lambda key, jpeg: None, speed=0.5, clock=lambda: clock.now, sleep=clock.sleep)

    assert clock.now - 100.0 == pytest.approx(4 * 0.2 + 0.15), "frame i goes out at i / (fps * speed): the delays do not pile up"
    assert min(clock.slept) >= 0.0


def test_play_refuses_a_speed_of_zero():
    with pytest.raises(ValueError):
        play([], 30.0, print, print, speed=0.0)
