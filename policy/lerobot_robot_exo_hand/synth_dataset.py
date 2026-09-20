"""A fake dataset in the format that `lerobot-record` writes with `ExoHand`, for the smoke test.

    python -m lerobot_robot_exo_hand.synth_dataset --out policy/datasets/synth

Noise images and sine-wave fingers: a number trained on it has no meaning. The features come from
`ExoHand` itself, so the fake dataset changes with the recorder.
"""

import argparse
import shutil
from pathlib import Path

import numpy as np

from .config_exo_hand import ExoHandConfig
from .convert import KEYS
from .exo_hand import ExoHand

FPS = 30


def generate(out: Path, episodes: int = 5, frames: int = 60, config: ExoHandConfig | None = None) -> Path:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.utils.feature_utils import hw_to_dataset_features

    robot = ExoHand(config or ExoHandConfig(host="unused", id="synth"))
    features = {**hw_to_dataset_features(robot.action_features, "action"),
                **hw_to_dataset_features(robot.observation_features, "observation")}
    dataset = LeRobotDataset.create(out.name, fps=FPS, root=out, robot_type=robot.name, features=features, use_videos=True)
    rng = np.random.default_rng(0)
    phase = np.linspace(0, 1, len(KEYS), endpoint=False)
    for episode in range(episodes):
        for t in range(frames):
            # one close and one release per episode, each finger a little later than the one before
            wave = (0.5 - 0.5 * np.cos(2 * np.pi * (t / frames - 0.2 * phase + 0.1 * episode))).astype(np.float32)
            row = {"action": wave, "observation.state": wave * np.float32(0.9), "task": "grasp the object"}
            for key, feature in features.items():
                if feature["dtype"] == "video":
                    row[key] = rng.integers(0, 256, feature["shape"], np.uint8)
            dataset.add_frame(row)
        dataset.save_episode()
    if hasattr(dataset, "finalize"):
        dataset.finalize()
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=5)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--force", action="store_true", help="replace an existing folder")
    args = parser.parse_args()
    if args.out.exists() and args.force:
        shutil.rmtree(args.out)
    print(generate(args.out, args.episodes, args.frames))
