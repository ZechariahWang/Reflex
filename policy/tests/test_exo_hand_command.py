from types import SimpleNamespace

import pytest
from lerobot.teleoperators.config import TeleoperatorConfig
from lerobot.teleoperators.utils import make_teleoperator_from_config

from lerobot_robot_exo_hand import (
    ExoHand,
    ExoHandCommand,
    ExoHandCommandConfig,
    ExoHandConfig,
    exo_hand_leader,
)


@pytest.fixture
def clock(monkeypatch):
    now = SimpleNamespace(value=100.0)
    monkeypatch.setattr(exo_hand_leader.time, "monotonic", lambda: now.value)
    return now


@pytest.fixture
def teleop(tmp_path, clock):
    return ExoHandCommand(ExoHandCommandConfig(host="unused", calibration_dir=tmp_path))


def test_lerobot_finds_the_teleoperator_from_its_config(tmp_path):
    config = ExoHandCommandConfig(host="unused", calibration_dir=tmp_path)
    assert TeleoperatorConfig.get_choice_class("exo_hand_command") is ExoHandCommandConfig
    assert isinstance(make_teleoperator_from_config(config), ExoHandCommand)


def test_action_is_the_state_until_somebody_commands_then_the_last_command(teleop, tmp_path):
    teleop._on_state({"data": [0.0, 0.1, 0.2, 0.3, 0.4]})
    assert teleop.get_action()["index.pos"] == 0.1

    teleop._on_command({"data": [1.0] * 5})
    teleop._on_command({"data": [0.5, 1.0, 1.0, 0.0, 0.0]})
    action = teleop.get_action()

    robot = ExoHand(ExoHandConfig(host="unused", calibration_dir=tmp_path))
    assert action.keys() == robot.action_features.keys() == teleop.action_features.keys()
    assert action["thumb.pos"] == 0.5 and action["index.pos"] == 1.0  # past the contact point: not the state


def test_command_stays_valid_while_the_state_is_fresh_because_it_is_published_only_on_change(teleop, clock):
    teleop._on_state({"data": [0.0] * 5})
    teleop._on_command({"data": [1.0] * 5})
    clock.value += 5.0
    teleop._on_state({"data": [0.6] * 5})
    assert teleop.get_action()["ring.pos"] == 1.0


def test_get_action_fails_on_a_dead_link(teleop, clock):
    with pytest.raises(ConnectionError):
        teleop.get_action()
    teleop._on_state({"data": [0.0] * 5})
    teleop._on_command({"data": [1.0] * 5})
    clock.value += 0.4
    with pytest.raises(ConnectionError):
        teleop.get_action()


def test_get_action_refuses_a_passive_hal_that_ignores_the_commands(teleop):
    teleop._on_state({"data": [0.0] * 5})
    teleop.get_action()  # mode unknown: a HAL with no passive mode is fine
    teleop._on_passive({"data": True})
    with pytest.raises(RuntimeError):
        teleop.get_action()


def test_malformed_command_is_an_error(teleop):
    teleop._on_state({"data": [0.0] * 5})
    teleop._on_command({"data": [1.0] * 4})
    with pytest.raises(ValueError):
        teleop.get_action()
