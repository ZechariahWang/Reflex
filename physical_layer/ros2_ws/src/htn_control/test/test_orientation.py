"""The hand's orientation from gyro + accelerometer: the filter alone, on synthetic samples."""
import math

import numpy as np
import pytest

from htn_control.orientation import GRAVITY, OrientationFilter, from_rpy, quaternion, rotation, yaw_of

DT = 1 / 200
UP = np.array([0.0, 0.0, GRAVITY])


def run(f, seconds, gyro, r_true=None):
    """Feed a constant body rate; the accelerometer reads gravity as the true orientation sees it."""
    r_true = np.eye(3) if r_true is None else r_true
    for _ in range(int(seconds / DT)):
        r_true = r_true @ rotation(np.asarray(gyro) * DT)
        f.update(gyro, r_true.T @ UP, DT)
    return r_true


def test_turning_flat_on_the_table_is_yaw_and_nothing_else():
    f = OrientationFilter()
    run(f, 0.1, [0, 0, 0])
    run(f, 2.0, [0, 0, math.radians(45)])  # 90 deg to the left
    assert math.degrees(yaw_of(f.r)) == pytest.approx(90.0, abs=1.0)
    assert f.r[2, 2] == pytest.approx(1.0, abs=1e-3), 'still flat'


def test_yaw_is_about_the_vertical_however_the_hand_is_held():
    tilted = from_rpy(math.radians(40), math.radians(-25), 0.0)
    f = OrientationFilter()
    run(f, 0.1, [0, 0, 0], tilted)
    assert math.degrees(yaw_of(f.r)) == pytest.approx(0.0, abs=0.5), 'the start is yaw 0, tilted or not'
    world_rate = np.array([0, 0, math.radians(30)])  # turn about the vertical, not about a body axis
    r_true = tilted
    for _ in range(int(2.0 / DT)):
        body_rate = r_true.T @ world_rate
        r_true = r_true @ rotation(body_rate * DT)
        f.update(body_rate, r_true.T @ UP, DT)
    assert math.degrees(yaw_of(f.r)) == pytest.approx(60.0, abs=1.5)


def test_a_wrong_tilt_is_pulled_back_to_gravity():
    f = OrientationFilter()
    run(f, 0.1, [0, 0, 0])
    f.r = from_rpy(math.radians(20), 0.0, 0.0) @ f.r  # as after a knock the accelerometer was not trusted in
    run(f, 3.0, [0, 0, 0])
    assert f.r[2, 2] == pytest.approx(1.0, abs=2e-3)


def test_the_gyro_bias_is_learnt_at_rest_so_the_yaw_stops_drifting():
    bias = np.array([0.004, -0.003, 0.01])  # rad/s: 0.57 deg/s of yaw drift if it stayed
    f = OrientationFilter()
    for _ in range(int(20.0 / DT)):
        f.update(bias, UP, DT)
    assert f.bias == pytest.approx(bias, abs=1e-3)
    before = yaw_of(f.r)
    for _ in range(int(10.0 / DT)):
        f.update(bias, UP, DT)
    assert math.degrees(abs(yaw_of(f.r) - before)) < 0.6, 'under 0.06 deg/s left'


def test_a_shake_does_not_tilt_the_hand():
    f = OrientationFilter()
    run(f, 0.1, [0, 0, 0])
    for i in range(400):
        f.update([0, 0, 0], UP + [6.0 * math.sin(i / 5), 0.0, 0.0], DT)  # 6 m/s^2 sideways: not gravity
    assert f.r[2, 2] == pytest.approx(1.0, abs=5e-3)


def test_reset_makes_the_present_heading_zero_and_keeps_the_tilt():
    f = OrientationFilter()
    run(f, 0.1, [0, 0, 0], from_rpy(0.3, 0.0, 0.0))
    run(f, 1.0, [0, 0, 1.0], from_rpy(0.3, 0.0, 0.0))
    tilt = f.r[2, 2]
    f.reset_yaw()
    assert yaw_of(f.r) == pytest.approx(0.0, abs=1e-9) and f.r[2, 2] == pytest.approx(tilt)


def test_quaternion_of_a_rotation():
    assert quaternion(np.eye(3)) == pytest.approx((0, 0, 0, 1))
    assert quaternion(from_rpy(0, 0, math.pi / 2)) == pytest.approx((0, 0, math.sqrt(0.5), math.sqrt(0.5)))
    assert quaternion(from_rpy(0, 0, math.pi)) == pytest.approx((0, 0, 1, 0), abs=1e-6)
