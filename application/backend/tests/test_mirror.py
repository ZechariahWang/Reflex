import numpy as np
import pytest

from app.mirror.calibration import Calibration
from app.mirror.curl import bends
from app.mirror.engage import Engage
from app.mirror.one_euro import OneEuro
from app.mirror.synthetic import JOINT_MAX_RAD, hand

PINCH = [1.0, 1.0, 0.0, 0.0, 0.0]


def test_straight_fingers_have_no_bend_and_bent_ones_the_sum_of_their_joints():
    assert bends(hand([0.0] * 5)) == pytest.approx([0.0] * 5, abs=1e-6)
    curls = [0.2, 1.0, 0.5, 0.0, 0.8]
    assert bends(hand(curls)) == pytest.approx([3 * JOINT_MAX_RAD * c for c in curls])


def test_bends_ignore_where_the_hand_is_how_big_and_how_it_is_turned():
    points = hand([0.3, 0.9, 0.1, 0.6, 1.0])
    a, b, c = 0.7, -1.1, 2.3
    rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    moved = 2.5 * points @ (rx @ ry @ rz).T + np.array([0.4, -0.2, 1.5])
    assert bends(moved) == pytest.approx(bends(points))


def test_calibration_scales_between_open_and_fist_and_clips():
    calibration = Calibration(open=np.full(5, 0.5), fist=np.full(5, 2.5))
    assert calibration.curls(np.array([0.5, 1.5, 2.5, 0.0, 9.0])) == pytest.approx([0.0, 0.5, 1.0, 0.0, 1.0])


def test_calibration_refuses_a_finger_that_did_not_move():
    fist = np.full(5, 2.5)
    fist[2] = 0.55
    with pytest.raises(ValueError):
        Calibration(open=np.full(5, 0.5), fist=fist)


def test_one_euro_calms_jitter_but_follows_a_fast_move():
    rng = np.random.default_rng(0)
    noisy = 0.5 + rng.normal(0, 0.02, (120, 5))
    smooth = OneEuro(min_cutoff=1.0, beta=1.0)
    out = np.array([smooth(x, i / 30) for i, x in enumerate(noisy)])
    assert out[30:].std() < 0.5 * noisy[30:].std()

    step = OneEuro(min_cutoff=1.0, beta=1.0)
    step(np.zeros(5), 0.0)
    for i in range(1, 10):
        value = step(np.ones(5), i / 30)
    assert value.min() > 0.9


def test_one_euro_forgets_after_a_reset():
    smooth = OneEuro(min_cutoff=1.0, beta=0.0)
    smooth(np.zeros(5), 0.0)
    smooth.reset()
    assert smooth(np.ones(5), 1.0) == pytest.approx(np.ones(5))


def test_engage_is_off_until_started():
    machine = Engage()
    assert machine.update(PINCH) == "off"
    assert machine.command is None


def test_engage_follows_at_once_whatever_the_hand_holds():
    machine = Engage()
    machine.start([0.0] * 5)
    assert machine.command == [0.0] * 5
    assert machine.update(PINCH) == "following"
    assert machine.command == PINCH


def test_engage_holds_through_a_dropout_and_resumes_at_once():
    machine = Engage()
    machine.start(PINCH)
    machine.update(PINCH)
    assert machine.update(None) == "no_hand"
    assert machine.command == PINCH
    assert machine.update([0.0] * 5) == "following"
    assert machine.command == [0.0] * 5


def test_engage_is_off_again_after_a_stop():
    machine = Engage()
    machine.start(PINCH)
    machine.stop()
    assert machine.update(PINCH) == "off" and machine.command is None
