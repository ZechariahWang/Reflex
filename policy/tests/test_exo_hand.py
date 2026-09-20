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
        data = message["data"]
        self.sent.append(list(data) if isinstance(data, list) else data)


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


@pytest.fixture
def wrist_only(robot):
    """The same robot with no head camera: the old datasets and a bench with no phone."""
    robot.config.head_topic = ""
    return robot


def action(value):
    return dict.fromkeys(KEYS, value)


def test_lerobot_finds_the_robot_from_its_config(tmp_path):
    assert RobotConfig.get_choice_class("exo_hand") is ExoHandConfig
    assert isinstance(make_robot_from_config(ExoHandConfig(host="unused", calibration_dir=tmp_path)), ExoHand)


def test_features_are_known_before_connect(tmp_path):
    config = ExoHandConfig(
        host="unused", calibration_dir=tmp_path, width=320, height=240, head_width=160, head_height=120
    )
    robot = ExoHand(config)

    assert robot.observation_features == {
        **dict.fromkeys(KEYS, float),
        "camera1": (120, 160, 3),
        "camera2": (240, 320, 3),
    }
    assert robot.action_features == dict.fromkeys(KEYS, float)
    assert not robot.is_connected
    assert len(robot.cameras) == 2  # lerobot-record sizes its image writer from this


def test_features_with_no_head_camera(tmp_path):
    robot = ExoHand(ExoHandConfig(host="unused", calibration_dir=tmp_path, head_topic=""))

    assert robot.observation_features == {**dict.fromkeys(KEYS, float), "camera2": (480, 640, 3)}
    assert len(robot.cameras) == 1


def test_get_observation_returns_latest_state_and_frame(robot):
    robot._on_state({"data": [0.9] * 5})
    robot._on_state({"data": [0.0, 0.1, 0.2, 0.3, 0.4]})
    robot._on_color(jpeg_message())
    robot._on_head(jpeg_message(height=240, width=320))
    robot.config.head_width, robot.config.head_height = 320, 240

    obs = robot.get_observation()

    assert obs["index.pos"] == 0.1 and obs["pinky.pos"] == 0.4
    assert obs["camera1"].shape == (240, 320, 3)
    assert obs["camera2"].shape == (480, 640, 3)


def test_get_observation_fails_until_all_streams_arrived(robot):
    robot._on_state({"data": [0.0] * 5})
    with pytest.raises(ConnectionError):
        robot.get_observation()
    robot._on_color(jpeg_message())
    with pytest.raises(ConnectionError):
        robot.get_observation()


def test_get_observation_fails_on_a_frozen_head_stream(robot, clock):
    robot._on_head(jpeg_message())
    clock.value += 0.4
    robot._on_state({"data": [0.0] * 5})
    robot._on_color(jpeg_message())  # state and wrist frame are fresh, the head frame is 0.4 s old

    with pytest.raises(ConnectionError):
        robot.get_observation()


def test_get_observation_with_no_head_camera(wrist_only):
    wrist_only._on_state({"data": [0.0] * 5})
    wrist_only._on_color(jpeg_message())

    assert list(wrist_only.get_observation()) == [*KEYS, "camera2"]


def test_get_observation_fails_on_a_frozen_stream(robot, clock):
    robot._on_state({"data": [0.0] * 5})
    robot._on_color(jpeg_message())
    clock.value += 0.2
    robot._on_state({"data": [0.0] * 5})
    robot._on_head(jpeg_message())
    clock.value += 0.2  # state is fresh, the frame is 0.4 s old

    with pytest.raises(ConnectionError):
        robot.get_observation()


def test_get_observation_rejects_a_frame_of_the_wrong_size(robot):
    robot._on_state({"data": [0.0] * 5})
    robot._on_color(jpeg_message(height=240, width=320))
    robot._on_head(jpeg_message())
    with pytest.raises(ValueError):
        robot.get_observation()


def test_get_observation_rejects_a_head_frame_of_the_wrong_size(robot):
    robot._on_state({"data": [0.0] * 5})
    robot._on_color(jpeg_message())
    robot._on_head(jpeg_message(height=240, width=320))
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


def test_send_action_refuses_while_the_hal_ignores_commands(robot):
    robot._on_passive({"data": True})
    with pytest.raises(RuntimeError):
        robot.send_action(action(0.5))

    robot.config.passive = True  # a recording: nothing is published, so the HAL mode is no problem
    assert robot.send_action(action(0.5)) == action(0.5)


@pytest.fixture
def gated(robot):
    """The robot of run_policy.sh: the console's switch decides if an action reaches the hand."""
    robot.config.enable_topic = "/policy/enabled"
    robot._active_out = FakeTopic()
    return robot


def test_a_gated_policy_moves_nothing_until_the_console_enables_it(gated):
    gated._on_passive({"data": True})  # the policy service stays up while a person records demonstrations

    assert gated.send_action(action(0.8)) == action(0.8)
    assert gated._command_out.sent == []

    gated._on_passive({"data": False})
    gated._on_enabled({"data": True})
    gated.send_action(action(0.8))
    assert gated._command_out.sent == [[0.8] * 5]


def test_disabling_the_policy_opens_the_hand_once_and_drops_the_actions_after_it(gated):
    gated._on_enabled({"data": True})
    gated.send_action(action(0.8))

    gated._on_enabled({"data": False})
    gated._on_enabled({"data": False})
    gated.send_action(action(0.9))

    assert gated._command_out.sent == [[0.8] * 5, [0.0] * 5]


def test_a_gated_policy_says_once_a_second_if_its_actions_reach_the_hand(gated, clock):
    for message in (gated._on_color, gated._on_head):
        message(jpeg_message())
    gated._on_state({"data": [0.0] * 5})

    gated.get_observation()
    gated.get_observation()
    gated._on_enabled({"data": True})
    assert gated._active_out.sent == [False, True], "a change of the switch is said at once"

    clock.value += 0.2
    gated._on_state({"data": [0.0] * 5})
    gated.get_observation()
    assert gated._active_out.sent == [False, True]
