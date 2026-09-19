import numpy as np
import pytest
from lerobot.datasets.lerobot_dataset import LeRobotDataset

from lerobot_robot_exo_hand.convert import KEYS
from lerobot_robot_exo_hand.label import label, relabel


def ramp(n=6):
    return np.linspace(0.0, 0.5, n)[:, None].repeat(5, axis=1)


def test_label_takes_the_state_k_frames_later_and_holds_the_last_one():
    states = ramp()

    out = label(states, k=2, gain=0.0)

    assert np.allclose(out[:4], states[2:])
    assert np.allclose(out[4:], states[-1])


def test_label_gain_pushes_past_contact_but_keeps_open_and_the_limit():
    states = np.array([[0.0, 0.5, 0.9, 1.0, 0.25]])

    out = label(states, k=0, gain=0.2)

    assert np.allclose(out, [[0.0, 0.6, 1.0, 1.0, 0.3]])


def test_label_without_shift_and_gain_is_the_identity():
    assert np.allclose(label(ramp(), k=0, gain=0.0), ramp())


def test_label_rejects_a_negative_shift():
    with pytest.raises(ValueError):
        label(ramp(), k=-1, gain=0.0)


def test_relabel_shifts_inside_each_episode_and_keeps_the_raw_dataset(tmp_path):
    feature = {"dtype": "float32", "shape": (5,), "names": list(KEYS)}
    raw = LeRobotDataset.create(
        "test/raw",
        fps=15,
        features={"observation.state": feature, "action": feature},
        root=tmp_path / "raw",
        use_videos=False,
    )
    episodes = (ramp(), ramp()[::-1].copy())
    for states in episodes:
        for state in states.astype(np.float32):
            raw.add_frame({"observation.state": state, "action": state, "task": "grasp"})
        raw.save_episode()
    raw.finalize()

    out_root = relabel(tmp_path / "raw", k=2, gain=0.2)

    assert out_root == tmp_path / "raw_k2_g20"
    out = LeRobotDataset("test/raw_k2_g20", root=out_root)
    actions = np.stack([np.asarray(frame["action"]) for frame in out])
    expected = np.concatenate([label(states, 2, 0.2) for states in episodes])
    assert np.allclose(actions, expected, atol=1e-6)
    assert np.allclose(out.meta.stats["action"]["max"], expected.max(axis=0), atol=1e-6)
    untouched = LeRobotDataset("test/raw", root=tmp_path / "raw")
    assert np.allclose(np.asarray(untouched[0]["action"]), episodes[0][0])
