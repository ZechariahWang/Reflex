from types import SimpleNamespace

import pytest
from lerobot.teleoperators.config import TeleoperatorConfig
from lerobot.teleoperators.utils import make_teleoperator_from_config

from lerobot_robot_exo_hand import (
    ExoHand,
    ExoHandConfig,
    ExoHandLeader,
    ExoHandLeaderConfig,
    exo_hand_leader,
)


@pytest.fixture
def clock(monkeypatch):
    now = SimpleNamespace(value=100.0)
    monkeypatch.setattr(exo_hand_leader.time, "monotonic", lambda: now.value)
    return now


@pytest.fixture
def leader(tmp_path, clock):
    return ExoHandLeader(ExoHandLeaderConfig(host="unused", calibration_dir=tmp_path))


def test_lerobot_finds_the_teleoperator_from_its_config(tmp_path):
    config = ExoHandLeaderConfig(host="unused", calibration_dir=tmp_path)
    assert TeleoperatorConfig.get_choice_class("exo_hand_leader") is ExoHandLeaderConfig
    assert isinstance(make_teleoperator_from_config(config), ExoHandLeader)


def test_get_action_is_the_latest_state_in_the_action_keys_of_the_robot(leader, tmp_path):
    leader._on_passive({"data": True})
    leader._on_state({"data": [0.9] * 5})
    leader._on_state({"data": [0.0, 0.1, 0.2, 0.3, 0.4]})

    action = leader.get_action()

    robot = ExoHand(ExoHandConfig(host="unused", calibration_dir=tmp_path))
    assert action.keys() == robot.action_features.keys() == leader.action_features.keys()
    assert action["index.pos"] == 0.1 and action["pinky.pos"] == 0.4


def test_get_action_fails_without_a_state_and_on_a_frozen_stream(leader, clock):
    leader._on_passive({"data": True})
    with pytest.raises(ConnectionError):
        leader.get_action()
    leader._on_state({"data": [0.0] * 5})
    clock.value += 0.4
    with pytest.raises(ConnectionError):
        leader.get_action()


def test_get_action_refuses_a_hal_with_torque_unless_told_otherwise(leader):
    leader._on_state({"data": [0.0] * 5})
    with pytest.raises(RuntimeError):  # mode unknown
        leader.get_action()
    leader._on_passive({"data": True})
    leader.get_action()
    leader._on_passive({"data": False})  # somebody switched the torque on in the middle of a session
    with pytest.raises(RuntimeError):
        leader.get_action()

    leader.config.require_passive = False
    leader.get_action()
