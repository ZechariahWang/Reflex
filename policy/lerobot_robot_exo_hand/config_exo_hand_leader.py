from dataclasses import dataclass

from lerobot.teleoperators.config import TeleoperatorConfig


@TeleoperatorConfig.register_subclass("exo_hand_leader")
@dataclass(kw_only=True)
class ExoHandLeaderConfig(TeleoperatorConfig):
    # Machine that runs rosbridge (the ROS machine of the hand)
    host: str
    port: int = 9090
    # Oldest state that get_action() accepts
    max_age_s: float = 0.3
    connect_timeout_s: float = 10.0
