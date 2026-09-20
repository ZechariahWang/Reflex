import numpy as np
import pytest
import torch

from lerobot_robot_exo_hand.heldout import collect, errors, near_crossing, split


@pytest.mark.parametrize("episodes", [1, 2, 9, 10, 50, 53])
def test_split_is_disjoint_complete_and_never_empty(episodes):
    train, heldout = split(episodes)

    assert sorted(train + heldout) == list(range(episodes))
    assert len(heldout) == max(1, round(episodes * 0.1))


def test_split_is_the_same_for_the_same_seed_and_differs_for_another():
    assert split(50, seed=3) == split(50, seed=3)
    assert split(50, seed=3) != split(50, seed=4)


def test_near_crossing_marks_the_frames_around_a_close_and_stops_at_the_episode_border():
    # episode 0 closes between frame 4 and 5; episode 1 starts closed, which is no crossing
    action = np.zeros((16, 5), np.float32)
    action[5:8, 1] = 0.9
    action[8:] = 0.9
    episode = np.array([0] * 8 + [1] * 8)

    assert np.flatnonzero(near_crossing(action, episode, frames=2)).tolist() == [3, 4, 5, 6]


def test_errors_are_mean_absolute_overall_per_finger_and_in_the_window():
    recorded = np.zeros((4, 5), np.float32)
    predicted = recorded.copy()
    predicted[:, 0] = 0.2
    predicted[0, 4] = 0.4
    window = np.array([True, False, False, False])

    result = errors(predicted, recorded, window)

    assert result["per_finger"] == pytest.approx({"thumb": 0.2, "index": 0, "middle": 0, "ring": 0, "pinky": 0.1})
    assert result["mae"] == pytest.approx(0.06)
    assert result["mae_near_crossing"] == pytest.approx(0.12)
    assert errors(predicted, recorded, np.zeros(4, bool))["mae_near_crossing"] is None


def test_collect_compares_the_first_action_of_each_chunk_on_every_nth_frame():
    frames = [{"action": torch.full((5,), float(i)), "observation.state": torch.zeros(5)} for i in range(6)]

    def predict(batch):  # a chunk of 3 actions; only the first one is right
        first = batch["action"] + 1
        return torch.stack([first, first * 0, first * 0], dim=1)

    indices, predicted, recorded = collect(predict, frames, stride=2, batch_size=2)

    assert indices.tolist() == [0, 2, 4]
    assert recorded[:, 0].tolist() == [0, 2, 4] and predicted[:, 0].tolist() == [1, 3, 5]
