"""Runtime configuration, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CORS_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
MOCK_URDF_PATH = Path(__file__).resolve().parent.parent / "mock" / "hand.urdf"
# The hand's meshes and linkage geometry are files, not topics: they come from the description
# package of this repository (the URDF itself still arrives over ROS).
REPO_DESCRIPTION_DIR = Path(__file__).resolve().parents[3] / "physical_layer" / "ros2_ws" / "src" / "htn_description"


@dataclass(frozen=True)
class Settings:
    rosbridge_host: str = "localhost"
    rosbridge_port: int = 9090
    mock: bool = False
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    depth_min_mm: int = 150
    depth_max_mm: int = 2000
    description_dir: Path = REPO_DESCRIPTION_DIR
    mirror_command_tolerance: float = 0.01
    mirror_min_cutoff: float = 1.5  # Hz: lower = calmer at rest
    mirror_beta: float = 1.0  # higher = less lag in a fast move
    # Ultralytics model for the objects around the hand; "" = no detector (objects stay empty)
    detect_model: str = "yolov8n.pt"
    # Passes per second at most, and torch threads: the detector shares the machine with the sim,
    # the sim's viewer and, on one laptop, the browser
    detect_hz: float = 4.0
    detect_threads: int = 2
    # Live ROS, but synthetic objects: a sim has no camera, and the map view still needs something to show
    mock_objects: bool = False
    # The wrist RealSense sits portrait on the hand: how far to turn its picture clockwise (0, 90, 180,
    # 270) to stand it upright - on the page, and for the object detector, which knows upright bottles.
    # The ROS topics, the recordings and the policy keep the picture as the camera sends it.
    # 270 was found on the hand: at 90 the picture stood on its head (the camera's top is on the
    # pinky side, not the thumb side that hand_params.yaml `camera.rpy` assumes).
    realsense_rotation: int = 270
    # Episodes recorded from the console (app/episodes.py). Next to the LeRobot datasets, ignored by git
    recordings_dir: Path = Path(__file__).resolve().parents[3] / "policy" / "datasets" / "console"
    # Pre-written movements for the Movement dropdown: the repo's movements/ folder (its README has the format)
    movements_dir: Path = Path(__file__).resolve().parents[3] / "movements"

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
            description_dir=Path(env.get("DESCRIPTION_DIR", str(REPO_DESCRIPTION_DIR))),
            mirror_command_tolerance=float(env.get("MIRROR_COMMAND_TOLERANCE", "0.01")),
            mirror_min_cutoff=float(env.get("MIRROR_MIN_CUTOFF", "1.5")),
            mirror_beta=float(env.get("MIRROR_BETA", "1.0")),
            detect_model=env.get("DETECT_MODEL", "yolov8n.pt").strip(),
            detect_hz=float(env.get("DETECT_HZ", "4")),
            detect_threads=int(env.get("DETECT_THREADS", "2")),
            mock_objects=env.get("MOCK_OBJECTS", "0") == "1",
            realsense_rotation=int(env.get("REALSENSE_ROTATION", "270")),
            recordings_dir=Path(env.get("RECORDINGS_DIR", str(cls.recordings_dir))),
            movements_dir=Path(env.get("MOVEMENTS_DIR", str(cls.movements_dir))),
        )
