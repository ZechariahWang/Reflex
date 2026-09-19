"""Turn a raw recording of backdriven fingers into training labels. Design: docs/specs/data-collection-design.md."""

import argparse
import shutil
from pathlib import Path

import numpy as np


def label(states: np.ndarray, k: int, gain: float) -> np.ndarray:
    """N x 5 states of one episode -> N x 5 actions: the state k frames later, pushed past contact by gain."""
    if k < 0 or gain < 0:
        raise ValueError(f"k and gain must not be negative: k={k}, gain={gain}")
    later = states[np.minimum(np.arange(len(states)) + k, len(states) - 1)]
    return np.minimum(1.0, later * (1.0 + gain))


def relabel(root: Path, k: int, gain: float) -> Path:
    """Copy the dataset at root to <root>_k<k>_g<gain %> and rewrite its action column from observation.state."""
    import pandas as pd
    from lerobot.datasets.dataset_tools import recompute_stats
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    root = Path(root)
    out = root.with_name(f"{root.name}_k{k}_g{round(gain * 100)}")
    shutil.copytree(root, out)
    for path in sorted((out / "data").glob("*/*.parquet")):
        frame = pd.read_parquet(path)
        for _, episode in frame.groupby("episode_index"):
            states = np.stack(episode["observation.state"].to_numpy())
            actions = label(states, k, gain).astype(states.dtype)
            frame.loc[episode.index, "action"] = pd.Series(list(actions), index=episode.index)
        frame.to_parquet(path)
    # ponytail: only meta/stats.json is recomputed; the per-episode stats in meta/episodes keep the raw
    # action values. Training normalizes with stats.json. Rewrite them if a tool starts to read them.
    recompute_stats(LeRobotDataset(out.name, root=out))
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="folder of the raw dataset")
    parser.add_argument("--k", type=int, default=3, help="frames between a state and the action it labels")
    parser.add_argument("--gain", type=float, default=0.2, help="0.2 puts a contact at 0.5 to a target of 0.6")
    args = parser.parse_args()
    print(relabel(args.root, args.k, args.gain))
