import base64
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from lerobot.robots.config import RobotConfig
from lerobot.robots.utils import make_robot_from_config

from lerobot_robot_exo_hand import ExoHand, ExoHandConfig, exo_hand
from lerobot_robot_exo_hand.convert import KEYS


class FakeTopic:
    def __init__(self):
        self.sent = []

    def publish(self, message):
        self.sent.append(list(message["data"]))


def jpeg_message(height=480, width=640):
    ok, jpeg = cv2.imencode(".jpg", np.zeros((height, width, 3), np.uint8))
    assert ok
    return {"data": base64.b64encode(jpeg.tobytes()).decode()}


@pytest.fixture
def clock(monkeypatch):
    now = SimpleNamespace(value=100.0)
    monkeypatch.setattr(exo_hand.time, "monotonic", lambda: now.value)
    return now


@pytest.fixture
def robot(tmp_path, clock):
    """An ExoHand wired to a fake publisher; messages are fed straight into its callbacks."""
    robot = ExoHand(ExoHandConfig(host="unused", calibration_dir=tmp_path))
    robot._ros = SimpleNamespace(is_connected=True, close=lambda: None)
    robot._command_out = FakeTopic()
    return robot


def action(value):
    return dict.fromkeys(KEYS, value)


def test_lerobot_finds_the_robot_from_its_config(tmp_path):
    assert RobotConfig.get_choice_class("exo_hand") is ExoHandConfig
    assert isinstance(make_robot_from_config(ExoHandConfig(host="unused", calibration_dir=tmp_path)), ExoHand)


def test_features_are_known_before_connect(tmp_path):
    robot = ExoHand(ExoHandConfig(host="unused", calibration_dir=tmp_path, width=320, height=240))

    assert robot.observation_features == {**dict.fromkeys(KEYS, float), "camera2": (240, 320, 3)}
    assert robot.action_features == dict.fromkeys(KEYS, float)
    assert not robot.is_connected


def test_get_observation_returns_latest_state_and_frame(robot):
    robot._on_state({"data": [0.9] * 5})
    robot._on_state({"data": [0.0, 0.1, 0.2, 0.3, 0.4]})
    robot._on_color(jpeg_message())

    obs = robot.get_observation()

    assert obs["index.pos"] == 0.1 and obs["pinky.pos"] == 0.4
    assert obs["camera2"].shape == (480, 640, 3)


def test_get_observation_fails_until_both_streams_arrived(robot):
    robot._on_state({"data": [0.0] * 5})
    with pytest.raises(ConnectionError):
        robot.get_observation()


def test_get_observation_fails_on_a_frozen_stream(robot, clock):
    robot._on_state({"data": [0.0] * 5})
    robot._on_color(jpeg_message())
    clock.value += 0.2
    robot._on_state({"data": [0.0] * 5})
    clock.value += 0.2  # state is fresh, the frame is 0.4 s old

    with pytest.raises(ConnectionError):
        robot.get_observation()


def test_get_observation_rejects_a_frame_of_the_wrong_size(robot):
    robot._on_state({"data": [0.0] * 5})
    robot._on_color(jpeg_message(height=240, width=320))
    with pytest.raises(ValueError):
        robot.get_observation()


def test_send_action_publishes_clamped_and_only_on_change(robot):
    assert robot.send_action(action(1.4)) == action(1.0)
    assert robot.send_action(action(0.995)) == action(1.0)  # inside the deadband: HAL still has 1.0
    assert robot.send_action(action(0.5)) == action(0.5)

    assert robot._command_out.sent == [[1.0] * 5, [0.5] * 5]


def test_send_action_does_not_echo_another_publisher(robot):
    robot._on_command({"data": [0.3] * 5})

    assert robot.send_action(action(0.3)) == action(0.3)
    assert robot._command_out.sent == []


def test_send_action_needs_a_connection(tmp_path):
    robot = ExoHand(ExoHandConfig(host="unused", calibration_dir=tmp_path))
    with pytest.raises(ConnectionError):
        robot.send_action(action(0.5))


def test_passive_send_action_publishes_nothing(robot):
    robot.config.passive = True

    assert robot.send_action(action(0.7)) == action(0.7)
    assert robot._command_out.sent == []
