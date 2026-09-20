"""The held-out episodes of a rental and the action error of a checkpoint on them.

    python -m lerobot_robot_exo_hand.heldout split --root policy/datasets/exo_grasp
    python -m lerobot_robot_exo_hand.heldout eval --root policy/datasets/exo_grasp \
        --checkpoint policy/outputs/train/<run>/<variant>/checkpoints/001000/pretrained_model \
        --variant <variant> --out docs/notes/training/runs/<run>/results.jsonl

`split` prints the two episode lists; every variant trains with `--dataset.episodes=<train list>`.
`eval` appends one JSON line: the mean absolute error between the first action of each predicted
chunk and the recorded action, on the 0 .. 1 command scale. `lerobot-train` has no validation
split, and its flow-matching loss has a random timestep and random noise, so it cannot compare
variants. Design: docs/specs/lambda-training-design.md.
"""

import argparse
import json
import random
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import torch

from .convert import FINGERS

WINDOW_S = 0.5
THRESHOLD = 0.5


def split(num_episodes: int, fraction: float = 0.1, seed: int = 0) -> tuple[list[int], list[int]]:
    count = max(1, round(num_episodes * fraction))
    heldout = sorted(random.Random(seed).sample(range(num_episodes), count))
    return [e for e in range(num_episodes) if e not in heldout], heldout


def near_crossing(action: np.ndarray, episode: np.ndarray, frames: int) -> np.ndarray:
    """The frames within `frames` of a close or a release: a finger's recorded action crosses 0.5."""
    closed = action > THRESHOLD
    crossed = (closed[1:] != closed[:-1]).any(axis=1) & (episode[1:] == episode[:-1])
    mask = np.zeros(len(action), bool)
    for before in np.flatnonzero(crossed):
        same = episode == episode[before]
        lo, hi = max(0, before + 1 - frames), before + 1 + frames
        mask[lo:hi] |= same[lo:hi]
    return mask


def errors(predicted: np.ndarray, recorded: np.ndarray, window: np.ndarray) -> dict:
    error = np.abs(predicted - recorded)
    return {
        "mae": float(error.mean()),
        "per_finger": {finger: float(value) for finger, value in zip(FINGERS, error.mean(axis=0))},
        "mae_near_crossing": float(error[window].mean()) if window.any() else None,
        "frames": len(error),
        "frames_near_crossing": int(window.sum()),
    }


def collect(predict: Callable[[dict], torch.Tensor], dataset: Sequence[dict], stride: int = 1,
            batch_size: int = 32) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`predict` maps a batch to action chunks (batch, chunk, 5). Returns the frame indices, the
    first action of each chunk and the recorded actions."""
    indices = list(range(0, len(dataset), stride))
    loader = torch.utils.data.DataLoader(torch.utils.data.Subset(dataset, indices), batch_size=batch_size)
    predicted, recorded = [], []
    for batch in loader:
        recorded.append(batch["action"].float().cpu().numpy())
        predicted.append(predict(batch)[:, 0].float().cpu().numpy())
    return np.array(indices), np.concatenate(predicted), np.concatenate(recorded)


def evaluate(checkpoint: Path, root: Path, episodes: list[int], stride: int, batch_size: int, device: str) -> dict:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

    dataset = LeRobotDataset(root.name, root=root, episodes=episodes)
    policy = SmolVLAPolicy.from_pretrained(checkpoint).to(device)
    preprocess, postprocess = make_pre_post_processors(
        policy.config, pretrained_path=str(checkpoint), preprocessor_overrides={"device_processor": {"device": device}})

    def predict(batch: dict) -> torch.Tensor:
        batch = preprocess({key: value for key, value in batch.items() if key != "action"})
        torch.manual_seed(0)  # the chunk starts from sampled noise: one checkpoint gives one number
        return postprocess(policy.predict_action_chunk(batch))

    indices, predicted, recorded = collect(predict, dataset, stride, batch_size)
    table = dataset.hf_dataset.with_format("numpy")
    window = near_crossing(np.stack(table["action"]), np.asarray(table["episode_index"]), round(WINDOW_S * dataset.fps))
    return errors(predicted, recorded, window[indices])


def num_episodes(root: Path) -> int:
    return json.loads((root / "meta" / "info.json").read_text())["total_episodes"]


def step_of(checkpoint: Path) -> int | None:
    name = checkpoint.resolve().parent.name  # checkpoints/<step>/pretrained_model; `last` is a link
    return int(name) if name.isdigit() else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("split", "eval"))
    parser.add_argument("--root", type=Path, required=True, help="the LeRobot dataset folder")
    parser.add_argument("--fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--checkpoint", type=Path, help="a pretrained_model folder")
    parser.add_argument("--variant", default="")
    parser.add_argument("--out", type=Path, help="results.jsonl, appended")
    parser.add_argument("--stride", type=int, default=1, help="every Nth held-out frame")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    train, heldout = split(num_episodes(args.root), args.fraction, args.seed)
    if args.command == "split":
        # no spaces: the value goes into --dataset.episodes= as it is
        print(f"train={json.dumps(train, separators=(',', ':'))}")
        print(f"heldout={json.dumps(heldout, separators=(',', ':'))}")
        return
    if not args.checkpoint or not args.out:
        parser.error("eval needs --checkpoint and --out")
    result = {"variant": args.variant, "step": step_of(args.checkpoint), "checkpoint": str(args.checkpoint),
              "heldout": heldout, "stride": args.stride,
              **evaluate(args.checkpoint, args.root, heldout, args.stride, args.batch_size, args.device)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "a") as f:
        f.write(json.dumps(result) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
