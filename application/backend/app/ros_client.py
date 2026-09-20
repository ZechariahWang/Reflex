"""rosbridge connection: subscriptions feed the Hub, commands go out to /hand/command.

roslibpy runs a Twisted reactor on its own daemon thread and invokes the
callbacks below on it. Its client factory retries forever with exponential
backoff, and every Topic replays its subscribe/advertise after a reconnect.
"""

from __future__ import annotations

import asyncio
import base64
import logging

import roslibpy

from .config import Settings
from .hub import Hub

LOGGER = logging.getLogger(__name__)

STATE_THROTTLE_MS = 16  # joint / hand state at up to 60 Hz: the viewer animates from these
IMAGE_THROTTLE_MS = 66
RECONNECT_INITIAL_S = 1.0
RECONNECT_MAX_S = 5.0

COLOR_TOPIC = "/camera/color/image_raw/compressed"
HEAD_COLOR_TOPIC = "/head_camera/color/image_raw/compressed"
DEPTH_TOPIC = "/camera/aligned_depth_to_color/image_raw/compressedDepth"
CAMERA_INFO_TOPIC = "/camera/aligned_depth_to_color/camera_info"
HEAD_DEPTH_TOPIC = "/head_camera/aligned_depth_to_color/image_raw/compressedDepth"
HEAD_CAMERA_INFO_TOPIC = "/head_camera/color/camera_info"  # the head depth is on the colour picture's pixels
HEAD_DEPTH_THROTTLE_MS = 200  # only the object detector reads it, a few times a second
CAMERA_INFO_THROTTLE_MS = 1000  # intrinsics do not change; one a second is plenty
MULTI_ARRAY = "std_msgs/Float64MultiArray"
COMPRESSED_IMAGE = "sensor_msgs/CompressedImage"


class RosClient:
    def __init__(self, settings: Settings, hub: Hub) -> None:
        self._settings = settings
        self._hub = hub
        self._ros: roslibpy.Ros | None = None
        self._command_out: roslibpy.Topic | None = None
        self._passive_service: roslibpy.Service | None = None

    @property
    def connected(self) -> bool:
        return self._ros is not None and bool(self._ros.is_connected)

    def start(self) -> None:
        logging.getLogger("twisted").setLevel(logging.WARNING)  # three lines per retry otherwise
        LOGGER.info("connecting to rosbridge at %s, retrying until it is up", self._settings.rosbridge_url)
        ros = roslibpy.Ros(self._settings.rosbridge_host, self._settings.rosbridge_port)
        ros.factory.set_initial_delay(RECONNECT_INITIAL_S)
        ros.factory.set_max_delay(RECONNECT_MAX_S)
        ros.on("ready", lambda _: LOGGER.info("rosbridge connected: %s", self._settings.rosbridge_url))
        ros.on("close", lambda _: LOGGER.warning("rosbridge connection lost, retrying"))

        hub = self._hub
        self._subscribe(ros, "/robot_description", "std_msgs/String", 0, lambda m: hub.on_urdf(m["data"]))
        self._subscribe(
            ros,
            "/joint_states",
            "sensor_msgs/JointState",
            STATE_THROTTLE_MS,
            lambda m: hub.on_joint_states(m["name"], m["position"]),
        )
        self._subscribe(ros, "/hand/state", MULTI_ARRAY, STATE_THROTTLE_MS, lambda m: hub.on_hand_state(m["data"]))
        self._subscribe(ros, "/hand/command", MULTI_ARRAY, STATE_THROTTLE_MS, lambda m: hub.on_hand_command(m["data"]))
        self._subscribe(
            ros, COLOR_TOPIC, COMPRESSED_IMAGE, IMAGE_THROTTLE_MS, lambda m: hub.on_color(base64.b64decode(m["data"]))
        )
        self._subscribe(
            ros, DEPTH_TOPIC, COMPRESSED_IMAGE, IMAGE_THROTTLE_MS, lambda m: hub.on_depth(base64.b64decode(m["data"]))
        )
        self._subscribe(
            ros,
            HEAD_COLOR_TOPIC,
            COMPRESSED_IMAGE,
            IMAGE_THROTTLE_MS,
            lambda m: hub.on_head_color(base64.b64decode(m["data"])),
        )

        self._subscribe(ros, CAMERA_INFO_TOPIC, "sensor_msgs/CameraInfo", CAMERA_INFO_THROTTLE_MS, hub.on_camera_info)
        self._subscribe(
            ros,
            HEAD_DEPTH_TOPIC,
            COMPRESSED_IMAGE,
            HEAD_DEPTH_THROTTLE_MS,
            lambda m: hub.on_head_depth(base64.b64decode(m["data"])),
        )
        self._subscribe(
            ros, HEAD_CAMERA_INFO_TOPIC, "sensor_msgs/CameraInfo", CAMERA_INFO_THROTTLE_MS, hub.on_head_camera_info
        )

        # Latched by the HAL: true while the torque is off and the fingers are backdriven
        self._subscribe(ros, "/hand/passive", "std_msgs/Bool", 0, lambda m: hub.on_passive(m["data"]))
        self._passive_service = roslibpy.Service(ros, "/hand/set_passive", "std_srvs/SetBool")

        # A Topic replays only one message on reconnect, so publishing gets its own.
        self._command_out = roslibpy.Topic(ros, "/hand/command", MULTI_ARRAY, queue_size=1)
        self._command_out.advertise()
        self._ros = ros
        ros.factory.manager.run()

    @staticmethod
    def _subscribe(ros: roslibpy.Ros, name: str, message_type: str, throttle_ms: int, callback) -> None:
        roslibpy.Topic(ros, name, message_type, throttle_rate=throttle_ms, queue_length=1).subscribe(callback)

    def send_command(self, values: list[float]) -> None:
        if self.connected and self._command_out is not None:
            self._command_out.publish(roslibpy.Message({"data": values}))

    def set_passive(self, passive: bool) -> None:
        """Ask the HAL for backdrive mode; the answer arrives on /hand/passive."""
        if self.connected and self._passive_service is not None:
            self._passive_service.call(
                roslibpy.ServiceRequest({"data": passive}),
                callback=lambda _: None,
                errback=lambda error: LOGGER.warning("set_passive failed: %s", error),
            )

    async def stop(self) -> None:
        if self._ros is None:
            return
        try:
            await asyncio.to_thread(self._ros.terminate)
        except roslibpy.core.RosTimeoutError:
            LOGGER.warning("rosbridge did not acknowledge the close; shutting down anyway")
