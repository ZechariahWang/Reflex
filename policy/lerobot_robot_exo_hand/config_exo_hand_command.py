from dataclasses import dataclass

from lerobot.teleoperators.config import TeleoperatorConfig

from .config_exo_hand_leader import ExoHandLeaderConfig


@TeleoperatorConfig.register_subclass("exo_hand_command")
@dataclass(kw_only=True)
class ExoHandCommandConfig(ExoHandLeaderConfig):
    # Not used: the torque is on in this recording, and a passive HAL is refused
    require_passive: bool = False
