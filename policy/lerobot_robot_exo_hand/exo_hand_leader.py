"""The backdriven hand as its own LeRobot leader: the action is the measured /hand/state.

For data collection only, with the servo torque off. label.py turns the recorded states into labels.
"""

import threading
import time

import roslibpy
from lerobot.teleoperators.teleoperator import Teleoperator

from .config_exo_hand_leader import ExoHandLeaderConfig
from .convert import KEYS, is_fresh
from .exo_hand import MULTI_ARRAY, STATE_TOPIC


class ExoHandLeader(Teleoperator):
    config_class = ExoHandLeaderConfig
    name = "exo_hand_leader"

    def __init__(self, config: ExoHandLeaderConfig):
        super().__init__(config)
        self.config = config
        self._ros: roslibpy.Ros | None = None
        self._lock = threading.Lock()
        self._state: list[float] | None = None
        self._state_stamp: float | None = None

    @property
    def action_features(self) -> dict[str, type]:
        return dict.fromkeys(KEYS, float)

    @property
    def feedback_features(self) -> dict[str, type]:
        return {}

    @property
    def is_connected(self) -> bool:
        return self._ros is not None and bool(self._ros.is_connected)

    # Calibration is in the HAL (hand_params.yaml)
    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    def send_feedback(self, feedback: dict) -> None:
        pass

    def connect(self, calibrate: bool = True) -> None:
        if self.is_connected:
            raise ConnectionError(f"{self} is already connected")
        ros = roslibpy.Ros(self.config.host, self.config.port)
        roslibpy.Topic(ros, STATE_TOPIC, MULTI_ARRAY, queue_length=1).subscribe(self._on_state)
        ros.run(timeout=self.config.connect_timeout_s)
        self._ros = ros

        deadline = time.monotonic() + self.config.connect_timeout_s
        while not self._fresh():
            if time.monotonic() > deadline:
                self.disconnect()
                raise ConnectionError(f"rosbridge is up but {STATE_TOPIC} is silent")
            time.sleep(0.05)

    def disconnect(self) -> None:
        if self._ros is not None:
            # close(), not terminate(): the Twisted reactor cannot start a second time in one process
            self._ros.close()
            self._ros = None

    def _on_state(self, message: dict) -> None:
        with self._lock:
            self._state, self._state_stamp = list(message["data"]), time.monotonic()

    def _fresh(self) -> bool:
        with self._lock:
            stamp = self._state_stamp
        return is_fresh((stamp,), time.monotonic(), self.config.max_age_s)

    def get_action(self) -> dict[str, float]:
        with self._lock:
            state, stamp = self._state, self._state_stamp
        # Without this a dead link labels the rest of the episode with one frozen pose
        if state is None or not is_fresh((stamp,), time.monotonic(), self.config.max_age_s):
            raise ConnectionError(f"no {STATE_TOPIC} from rosbridge within {self.config.max_age_s} s")
        if len(state) != len(KEYS):
            raise ValueError(f"state has {len(state)} values, expected {len(KEYS)}")
        return {key: float(value) for key, value in zip(KEYS, state)}
