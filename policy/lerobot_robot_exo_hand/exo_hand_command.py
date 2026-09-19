"""Whatever commands the hand as a LeRobot teleoperator: the action is the last /hand/command.

For data collection with the torque on (mirror teleop, sliders, keys). Record with
--robot.passive=true, or the robot publishes every command a second time.
"""

import roslibpy

from .config_exo_hand_command import ExoHandCommandConfig
from .exo_hand import COMMAND_TOPIC, MULTI_ARRAY, PASSIVE_TOPIC
from .exo_hand_leader import ExoHandLeader


class ExoHandCommand(ExoHandLeader):
    config_class = ExoHandCommandConfig
    name = "exo_hand_command"

    def __init__(self, config: ExoHandCommandConfig):
        super().__init__(config)
        self._command: list[float] | None = None

    def _subscribe(self, ros: roslibpy.Ros) -> None:
        super()._subscribe(ros)
        roslibpy.Topic(ros, COMMAND_TOPIC, MULTI_ARRAY, queue_length=1).subscribe(self._on_command)

    def _on_command(self, message: dict) -> None:
        with self._lock:
            self._command = list(message["data"])

    def _check_mode(self) -> None:
        if self._hal_passive:
            raise RuntimeError(
                f"the HAL reports passive mode on {PASSIVE_TOPIC}: it ignores {COMMAND_TOPIC}, so the "
                "recorded actions would move nothing. Switch it to active"
            )

    def get_action(self) -> dict[str, float]:
        self._check_mode()
        # Commands are published only on change, so the state is what proves the link is alive
        state = self._fresh_state()
        with self._lock:
            command = self._command
        # Nobody has commanded yet: the hand holds its pose
        return self._as_action(state if command is None else command)
