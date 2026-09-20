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
    HEAD_CAMERA,
    KEYS,
    decode_color,
    differs,
    is_fresh,
    to_command,
    to_observation,
)

STATE_TOPIC = "/hand/state"
COMMAND_TOPIC = "/hand/command"
PASSIVE_TOPIC = "/hand/passive"
MULTI_ARRAY = "std_msgs/Float64MultiArray"
COMPRESSED_IMAGE = "sensor_msgs/CompressedImage"
BOOL = "std_msgs/Bool"


class ExoHand(Robot):
    config_class = ExoHandConfig
    name = "exo_hand"

    def __init__(self, config: ExoHandConfig):
        super().__init__(config)
        self.config = config
        # lerobot-record counts these for its image writer threads; the frames come from rosbridge
        self.cameras = dict.fromkeys(self._image_shapes())
        self._ros: roslibpy.Ros | None = None
        self._command_out: roslibpy.Topic | None = None
        self._lock = threading.Lock()
        self._state: list[float] | None = None
        self._state_stamp: float | None = None
        self._jpeg: bytes | None = None
        self._jpeg_stamp: float | None = None
        self._head_jpeg: bytes | None = None
        self._head_stamp: float | None = None
        # Last command on the topic, from us or from another publisher
        self._last_command: list[float] | None = None
        # Latched by the HAL; None until it arrives (or with a HAL that has no passive mode)
        self._hal_passive: bool | None = None

    @property
    def observation_features(self) -> dict[str, type | tuple[int, int, int]]:
        return {**dict.fromkeys(KEYS, float), **self._image_shapes()}

    def _image_shapes(self) -> dict[str, tuple[int, int, int]]:
        shapes = {CAMERA: (self.config.height, self.config.width, 3)}
        if self.config.head_topic:
            shapes = {HEAD_CAMERA: (self.config.head_height, self.config.head_width, 3), **shapes}
        return shapes

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
            (self.config.head_topic, COMPRESSED_IMAGE, self._on_head),
            (COMMAND_TOPIC, MULTI_ARRAY, self._on_command),
            (PASSIVE_TOPIC, BOOL, self._on_passive),
        ):
            if not name:
                continue
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
                topics = (STATE_TOPIC, self.config.color_topic, self.config.head_topic)
                raise ConnectionError(f"rosbridge is up but one of {', '.join(filter(None, topics))} is silent")
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

    def _on_head(self, message: dict) -> None:
        jpeg = base64.b64decode(message["data"])
        with self._lock:
            self._head_jpeg, self._head_stamp = jpeg, time.monotonic()

    def _on_command(self, message: dict) -> None:
        with self._lock:
            self._last_command = list(message["data"])

    def _on_passive(self, message: dict) -> None:
        with self._lock:
            self._hal_passive = bool(message["data"])

    def _stamps(self) -> tuple[float | None, ...]:
        """Call with the lock held. A dead phone stops the client the same way as a dead RealSense."""
        stamps = (self._state_stamp, self._jpeg_stamp)
        return (*stamps, self._head_stamp) if self.config.head_topic else stamps

    def _fresh(self) -> bool:
        with self._lock:
            stamps = self._stamps()
        return is_fresh(stamps, time.monotonic(), self.config.max_age_s)

    def get_observation(self) -> dict:
        with self._lock:
            state, jpeg, head_jpeg = self._state, self._jpeg, self._head_jpeg
            stamps = self._stamps()
        # Without this a dead link returns the last frame forever and the policy acts on it
        if not is_fresh(stamps, time.monotonic(), self.config.max_age_s):
            raise ConnectionError(f"no data from rosbridge within {self.config.max_age_s} s")
        # The latest frame of each camera, not synchronized: at 15 fps the skew is at most ~70 ms
        shapes = self._image_shapes()
        rgb = self._decode(jpeg, self.config.color_topic, shapes[CAMERA])
        head = self._decode(head_jpeg, self.config.head_topic, shapes[HEAD_CAMERA]) if self.config.head_topic else None
        return to_observation(state, rgb, head)

    @staticmethod
    def _decode(jpeg: bytes, topic: str, expected: tuple[int, int, int]):
        rgb = decode_color(jpeg)
        if rgb.shape != expected:
            raise ValueError(f"{topic} is {rgb.shape}, the config says {expected}")
        return rgb

    def send_action(self, action: dict) -> dict:
        """Returns the command that the HAL has after the call, which is the old one inside the deadband."""
        if not self.is_connected or self._command_out is None:
            raise ConnectionError(f"{self} is not connected")
        command = to_command(action)
        if self.config.passive:
            return dict(zip(KEYS, command))
        with self._lock:
            # A passive HAL ignores every command: the policy would run and the hand would not move
            if self._hal_passive:
                raise RuntimeError(f"the HAL is passive (torque off) and ignores {COMMAND_TOPIC}; switch it to active")
            last = self._last_command
            publish = last is None or differs(command, last, self.config.command_tolerance)
            if publish:
                self._last_command = command
        if publish:
            self._command_out.publish(roslibpy.Message({"data": command}))
        return dict(zip(KEYS, command if publish else last))


def smoke(host: str, port: int, head_topic: str) -> None:
    """Against a running sim or hand: read one observation, close the hand, open it again."""
    with ExoHand(ExoHandConfig(host=host, port=port, head_topic=head_topic, id="smoke")) as robot:
        obs = robot.get_observation()
        print({key: (value.shape if key in (CAMERA, HEAD_CAMERA) else round(value, 3)) for key, value in obs.items()})
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
    parser.add_argument("--head-topic", default=ExoHandConfig.head_topic, help='"" = no head camera')
    args = parser.parse_args()
    smoke(args.host, args.port, args.head_topic)
