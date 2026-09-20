from pathlib import Path

import pytest
import yaml

REAL = Path(__file__).resolve().parents[2] / 'htn_description' / 'config' / 'hand_params.yaml'


@pytest.fixture
def params_file(tmp_path):
    """hand_params.yaml with a fixed servo calibration: the HAL tests must not change with
    whatever the real hand was last calibrated to."""
    params = yaml.safe_load(REAL.read_text())
    for n, finger in enumerate(['thumb', 'index', 'middle', 'ring', 'pinky'], start=1):
        params['servos'][finger] = {'id': n, 'open_step': 2048, 'closed_step': 3072}
    params['servos'].update(torque_limit=300, hold_torque=120)
    params['contact_stop'] = {'enabled': True, 'hold_lead': 0.03, 'release_travel': 0.15,
                              'blocked_current': 100, 'blocked_excess': 150}
    path = tmp_path / 'hand_params.yaml'
    path.write_text(yaml.safe_dump(params))
    return str(path)
