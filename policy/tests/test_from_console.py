import json

import cv2
import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset

from lerobot_robot_exo_hand.from_console import cameras_of, convert, usable


def console_dataset(root, episodes=2, ticks=6, head=True):
    root.mkdir(parents=True)
    (root / "meta.json").write_text(json.dumps({"fps": 30, "task": "grasp the bottle"}))
    for e in range(episodes):
        folder = root / f"episode_{e:03d}"
        lines = []
        for camera in ("camera1", "camera2"):
            (folder / camera).mkdir(parents=True)
        for tick in range(ticks):
            files = {}
            for camera, first in (("camera1", 2 if head else ticks), ("camera2", 0)):
                shown = tick - tick % 2  # 15 fps cameras under a 30 fps tick
                files[camera] = f"{camera}/{shown:06d}.jpg" if tick >= first else None
                if files[camera] and tick == shown:
                    cv2.imwrite(str(folder / files[camera]), np.full((48, 64, 3), 10 * tick, np.uint8))
            lines.append({"t": tick / 30, "state": [tick / 10] * 5, "action": [tick / 5] * 5, **files})
        (folder / "frames.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    return root


def test_the_ticks_before_every_camera_has_a_frame_are_left_out(tmp_path):
    root = console_dataset(tmp_path / "console" / "grasp")
    frames = [json.loads(line) for line in (root / "episode_000" / "frames.jsonl").read_text().splitlines()]

    assert cameras_of([frames]) == ["camera1", "camera2"]
    assert [round(f["t"] * 30) for f in usable(frames, ["camera1", "camera2"])] == [2, 3, 4, 5]


def test_convert_writes_a_lerobot_dataset_with_both_image_keys(tmp_path):
    out = convert(console_dataset(tmp_path / "console" / "grasp"))

    assert out == tmp_path / "grasp"
    dataset = LeRobotDataset("grasp", root=out)
    assert dataset.meta.total_episodes == 2 and len(dataset) == 8 and dataset.fps == 30
    assert set(dataset.meta.camera_keys) == {"observation.images.camera1", "observation.images.camera2"}
    assert np.allclose(dataset[0]["action"], [0.4] * 5) and np.allclose(dataset[0]["observation.state"], [0.2] * 5)


def test_a_recording_with_no_phone_has_only_the_wrist_camera(tmp_path):
    out = convert(console_dataset(tmp_path / "console" / "wrist", head=False))

    dataset = LeRobotDataset("wrist", root=out)
    assert dataset.meta.camera_keys == ["observation.images.camera2"] and len(dataset) == 12
