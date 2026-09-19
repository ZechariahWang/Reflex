from dataclasses import dataclass

from lerobot.robots.config import RobotConfig


@RobotConfig.register_subclass("exo_hand")
@dataclass(kw_only=True)
class ExoHandConfig(RobotConfig):
    # Machine that runs rosbridge (the ROS machine of the hand)
    host: str
    port: int = 9090
    # Never image_raw: rosbridge sends it as base64 JSON
    color_topic: str = "/camera/color/image_raw/compressed"
    # Size of the color stream; lerobot needs it before the first frame arrives
    width: int = 640
    height: int = 480
    # Oldest state or frame that get_observation() accepts
    max_age_s: float = 0.3
    # send_action() publishes only a command that differs by more than this
    command_tolerance: float = 0.01
    connect_timeout_s: float = 10.0
