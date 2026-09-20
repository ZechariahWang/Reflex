"""Episodes recorded in the web console -> a LeRobot dataset to train on.

    python -m lerobot_robot_exo_hand.from_console --root policy/datasets/console/exo_grasp

writes policy/datasets/exo_grasp (next to `console/`). The console's format is in
application/backend/app/episodes.py: per tick the state, the last command as the action, and the
newest JPEG of each camera. The LeRobot dataset has what `lerobot-record` writes with
`exo_hand_command`: `observation.state`, `action`, `observation.images.camera1` (head) and
`.camera2` (wrist). A dataset recorded with no phone has only camera2; the ticks before every
camera of the dataset has delivered its first frame are left out.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from .convert import CAMERA, HEAD_CAMERA, KEYS

CAMERAS = (HEAD_CAMERA, CAMERA)


def read_episode(episode: Path) -> list[dict]:
    with open(episode / "frames.jsonl") as f:
        return [json.loads(line) for line in f if line.strip()]


def cameras_of(episodes: list[list[dict]]) -> list[str]:
    """The cameras that every episode has frames of."""
    return [c for c in CAMERAS if all(any(frame.get(c) for frame in frames) for frames in episodes)]


def usable(frames: list[dict], cameras: list[str]) -> list[dict]:
    """From the first tick at which every camera has a frame."""
    return [frame for frame in frames if all(frame.get(camera) for camera in cameras)]


def features(cameras: list[str], height: int, width: int) -> dict:
    vector = {"dtype": "float32", "shape": (len(KEYS),), "names": list(KEYS)}
    video = {"dtype": "video", "shape": (height, width, 3), "names": ["height", "width", "channels"]}
    return {"action": vector, "observation.state": vector, **{f"observation.images.{camera}": video for camera in cameras}}


def convert(root: Path, out: Path | None = None) -> Path:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    root = Path(root)
    out = out or root.parent.parent / root.name
    meta = json.loads((root / "meta.json").read_text())
    folders = sorted(p for p in root.glob("episode_*") if (p / "frames.jsonl").is_file())
    episodes = [read_episode(folder) for folder in folders]
    cameras = cameras_of(episodes)
    if not cameras:
        raise ValueError(f"no camera has frames in every episode of {root}")
    first = cv2.imread(str(folders[0] / usable(episodes[0], cameras)[0][cameras[0]]))
    dataset = LeRobotDataset.create(out.name, fps=meta["fps"], root=out, robot_type="exo_hand",
                                    features=features(cameras, *first.shape[:2]), use_videos=True,
                                    image_writer_threads=8)
    for folder, frames in zip(folders, episodes):
        loaded: dict[str, np.ndarray] = {}  # a camera slower than the tick rate repeats its file: decode it once
        for frame in usable(frames, cameras):
            row = {"action": np.array(frame["action"], np.float32), "observation.state": np.array(frame["state"], np.float32),
                   "task": meta.get("task", "")}
            for camera in cameras:
                name = frame[camera]
                if name not in loaded:
                    loaded = {k: v for k, v in loaded.items() if not k.startswith(camera)}
                    loaded[name] = cv2.cvtColor(cv2.imread(str(folder / name)), cv2.COLOR_BGR2RGB)
                row[f"observation.images.{camera}"] = loaded[name]
            dataset.add_frame(row)
        dataset.save_episode()
    if hasattr(dataset, "finalize"):  # closes the parquet writers (lerobot >= 0.4)
        dataset.finalize()
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, help="a dataset of the console, e.g. policy/datasets/console/exo_grasp")
    parser.add_argument("--out", type=Path, default=None, help="default: policy/datasets/<name>")
    args = parser.parse_args()
    print(convert(args.root, args.out))
