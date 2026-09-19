import os

import yaml
from ament_index_python.packages import get_package_share_directory

# Finger order used by every command/state array in the project
FINGERS = ['thumb', 'index', 'middle', 'ring', 'pinky']


def default_params_file():
    return os.path.join(get_package_share_directory('htn_description'),
                        'config', 'hand_params.yaml')


def load_hand_params(path=''):
    """Load hand_params.yaml (the same file the URDF is generated from)."""
    with open(path or default_params_file()) as f:
        return yaml.safe_load(f)
