"""The exoskeleton hand as a LeRobot Robot, through the rosbridge websocket of the ROS machine.

roslibpy runs a Twisted reactor on its own daemon thread and invokes the
callbacks below on it. They only store the latest message; get_observation()
and send_action() never wait for the network.
"""

import argparse
import base64
import threading
import time

import roslibpy
from lerobot.robots.robot import Robot

from .config_exo_hand import ExoHandConfig
from .convert import (
    CAMERA,
    FINGERS,
    KEYS,
    decode_color,
    differs,
    is_fresh,
    to_command,
    to_observation,
)

STATE_TOPIC = "/hand/state"
COMMAND_TOPIC = "/hand/command"
MULTI_ARRAY = "std_msgs/Float64MultiArray"
COMPRESSED_IMAGE = "sensor_msgs/CompressedImage"


class ExoHand(Robot):
    config_class = ExoHandConfig
    name = "exo_hand"

    def __init__(self, config: ExoHandConfig):
        super().__init__(config)
        self.config = config
        self._ros: roslibpy.Ros | None = None
        self._command_out: roslibpy.Topic | None = None
        self._lock = threading.Lock()
        self._state: list[float] | None = None
        self._state_stamp: float | None = None
        self._jpeg: bytes | None = None
        self._jpeg_stamp: float | None = None
        # Last command on the topic, from us or from another publisher
        self._last_command: list[float] | None = None

    @property
    def observation_features(self) -> dict[str, type | tuple[int, int, int]]:
        return {**dict.fromkeys(KEYS, float), CAMERA: (self.config.height, self.config.width, 3)}

    @property
    def action_features(self) -> dict[str, type]:
        return dict.fromkeys(KEYS, float)

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

    def connect(self, calibrate: bool = True) -> None:
        if self.is_connected:
            raise ConnectionError(f"{self} is already connected")
        ros = roslibpy.Ros(self.config.host, self.config.port)
        for name, message_type, callback in (
            (STATE_TOPIC, MULTI_ARRAY, self._on_state),
            (self.config.color_topic, COMPRESSED_IMAGE, self._on_color),
            (COMMAND_TOPIC, MULTI_ARRAY, self._on_command),
        ):
            roslibpy.Topic(ros, name, message_type, queue_length=1).subscribe(callback)
        # A Topic replays only one of subscribe / advertise on reconnect, so publishing gets its own
        self._command_out = roslibpy.Topic(ros, COMMAND_TOPIC, MULTI_ARRAY, queue_size=1)
        self._command_out.advertise()
        ros.run(timeout=self.config.connect_timeout_s)
        self._ros = ros

        deadline = time.monotonic() + self.config.connect_timeout_s
        while not self._fresh():
            if time.monotonic() > deadline:
                self.disconnect()
                raise ConnectionError(
                    f"rosbridge is up but {STATE_TOPIC} or {self.config.color_topic} is silent"
                )
            time.sleep(0.05)

    def disconnect(self) -> None:
        if self._ros is not None:
            # close(), not terminate(): the Twisted reactor cannot start a second time in one process
            self._ros.close()
            self._ros = None

    def _on_state(self, message: dict) -> None:
        with self._lock:
            self._state, self._state_stamp = list(message["data"]), time.monotonic()

    def _on_color(self, message: dict) -> None:
        jpeg = base64.b64decode(message["data"])
        with self._lock:
            self._jpeg, self._jpeg_stamp = jpeg, time.monotonic()

    def _on_command(self, message: dict) -> None:
        with self._lock:
            self._last_command = list(message["data"])

    def _fresh(self) -> bool:
        with self._lock:
            stamps = (self._state_stamp, self._jpeg_stamp)
        return is_fresh(stamps, time.monotonic(), self.config.max_age_s)

    def get_observation(self) -> dict:
        with self._lock:
            state, jpeg = self._state, self._jpeg
            stamps = (self._state_stamp, self._jpeg_stamp)
        # Without this a dead link returns the last frame forever and the policy acts on it
        if state is None or jpeg is None or not is_fresh(stamps, time.monotonic(), self.config.max_age_s):
            raise ConnectionError(f"no data from rosbridge within {self.config.max_age_s} s")
        rgb = decode_color(jpeg)
        expected = (self.config.height, self.config.width, 3)
        if rgb.shape != expected:
            raise ValueError(f"{self.config.color_topic} is {rgb.shape}, the config says {expected}")
        return to_observation(state, rgb)

    def send_action(self, action: dict) -> dict:
        """Returns the command that the HAL has after the call, which is the old one inside the deadband."""
        if not self.is_connected or self._command_out is None:
            raise ConnectionError(f"{self} is not connected")
        command = to_command(action)
        if self.config.passive:
            return dict(zip(KEYS, command))
        with self._lock:
            last = self._last_command
            publish = last is None or differs(command, last, self.config.command_tolerance)
            if publish:
                self._last_command = command
        if publish:
            self._command_out.publish(roslibpy.Message({"data": command}))
        return dict(zip(KEYS, command if publish else last))


def smoke(host: str, port: int) -> None:
    """Against a running sim or hand: read one observation, close the hand, open it again."""
    with ExoHand(ExoHandConfig(host=host, port=port, id="smoke")) as robot:
        obs = robot.get_observation()
        print({key: (value.shape if key == CAMERA else round(value, 3)) for key, value in obs.items()})
        for target in (1.0, 0.0):
            robot.send_action(dict.fromkeys(KEYS, target))
            time.sleep(1.5)
            state = [robot.get_observation()[key] for key in KEYS]
            print(f"target {target}: state {[round(v, 2) for v in state]}")
            assert all(abs(v - target) < 0.1 for v in state), f"hand did not follow to {target}"
    print(f"ok: all {len(FINGERS)} fingers followed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=smoke.__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=9090)
    args = parser.parse_args()
    smoke(args.host, args.port)
