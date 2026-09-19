"""Runtime configuration, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CORS_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
MOCK_URDF_PATH = Path(__file__).resolve().parent.parent / "mock" / "hand.urdf"


@dataclass(frozen=True)
class Settings:
    rosbridge_host: str = "localhost"
    rosbridge_port: int = 9090
    mock: bool = False
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    depth_min_mm: int = 150
    depth_max_mm: int = 2000

    @property
    def rosbridge_url(self) -> str:
        return f"ws://{self.rosbridge_host}:{self.rosbridge_port}"

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        origins = env.get("CORS_ORIGINS", ",".join(DEFAULT_CORS_ORIGINS))
        return cls(
            rosbridge_host=env.get("ROSBRIDGE_HOST", "localhost"),
            rosbridge_port=int(env.get("ROSBRIDGE_PORT", "9090")),
            mock=env.get("MOCK", "0") == "1",
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            depth_min_mm=int(env.get("DEPTH_MIN_MM", "150")),
            depth_max_mm=int(env.get("DEPTH_MAX_MM", "2000")),
        )
