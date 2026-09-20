from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.utils.feature_utils import hw_to_dataset_features

from lerobot_robot_exo_hand.config_exo_hand import ExoHandConfig
from lerobot_robot_exo_hand.exo_hand import ExoHand
from lerobot_robot_exo_hand.synth_dataset import generate


def test_the_generated_dataset_has_the_features_that_lerobot_record_writes_with_exo_hand(tmp_path):
    config = ExoHandConfig(host="unused", id="test", width=64, height=48, head_width=64, head_height=48)
    out = generate(tmp_path / "synth", episodes=3, frames=8, config=config)

    dataset = LeRobotDataset("synth", root=out)
    robot = ExoHand(config)
    recorded = {**hw_to_dataset_features(robot.action_features, "action"),
                **hw_to_dataset_features(robot.observation_features, "observation")}
    for key, feature in recorded.items():
        written = dataset.meta.features[key]
        assert (written["dtype"], tuple(written["shape"]), written["names"]) == \
               (feature["dtype"], tuple(feature["shape"]), feature["names"]), key
    assert dataset.meta.total_episodes == 3 and len(dataset) == 24
    assert dataset[0]["task"]
