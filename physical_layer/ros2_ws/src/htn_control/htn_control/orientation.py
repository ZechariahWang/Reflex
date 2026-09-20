"""Orientation of the hand from the wrist camera's IMU (gyro + accelerometer, no magnetometer).

Pure maths, no ROS. A complementary filter: the gyro is integrated, the accelerometer pulls
the tilt back to gravity, and the gyro bias is learnt whenever the hand lies still. Yaw has
no absolute reference: it is relative to where the hand pointed at the start (or at the last
`reset_yaw()`), and it drifts slowly - the bias estimate is what keeps that slow.

Frames: `R` turns a vector of the BODY frame (the hand's base_link) into the WORLD frame
(z up, yaw 0 = the start). Everything that comes in is already in the body frame.
"""
import math

import numpy as np

GRAVITY = 9.81
ACCEL_GAIN = 0.02        # share of the tilt error taken out per sample
ACCEL_TRUST = 1.5        # m/s^2 off gravity and the accelerometer measures a motion, not the tilt
STILL_RATE = 0.05        # rad/s (after the bias) below which the hand counts as lying still ...
STILL_S = 1.0            # ... once it has for this long
BIAS_GAIN = 0.01


def rotation(axis_angle):
    """Rotation matrix of a rotation vector (Rodrigues)."""
    angle = np.linalg.norm(axis_angle)
    if angle < 1e-12:
        return np.eye(3)
    x, y, z = axis_angle / angle
    k = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.eye(3) + math.sin(angle) * k + (1.0 - math.cos(angle)) * k @ k


def from_rpy(roll, pitch, yaw):
    """URDF rpy: fixed axes x, y, z in that order."""
    return rotation(np.array([0.0, 0.0, yaw])) @ rotation(np.array([0.0, pitch, 0.0])) @ rotation(np.array([roll, 0.0, 0.0]))


def quaternion(r):
    """(x, y, z, w) of a rotation matrix."""
    w = math.sqrt(max(0.0, 1.0 + r[0, 0] + r[1, 1] + r[2, 2])) / 2.0
    if w > 1e-6:
        return ((r[2, 1] - r[1, 2]) / (4 * w), (r[0, 2] - r[2, 0]) / (4 * w), (r[1, 0] - r[0, 1]) / (4 * w), w)
    x = math.sqrt(max(0.0, 1.0 + r[0, 0] - r[1, 1] - r[2, 2])) / 2.0  # a half turn: w = 0
    y = math.sqrt(max(0.0, 1.0 - r[0, 0] + r[1, 1] - r[2, 2])) / 2.0
    z = math.sqrt(max(0.0, 1.0 - r[0, 0] - r[1, 1] + r[2, 2])) / 2.0
    return (x, math.copysign(y, r[0, 1] + r[1, 0]), math.copysign(z, r[0, 2] + r[2, 0]), 0.0)


def yaw_of(r):
    return math.atan2(r[1, 0], r[0, 0])


class OrientationFilter:

    def __init__(self):
        self.r = None               # world <- body; None until the first accelerometer sample
        self.bias = np.zeros(3)     # of the gyro, rad/s
        self.still_for = 0.0

    def reset_yaw(self):
        """Where the hand points now becomes yaw 0."""
        if self.r is not None:
            self.r = rotation(np.array([0.0, 0.0, -yaw_of(self.r)])) @ self.r

    def update(self, gyro, accel, dt):
        """One IMU sample in the body frame: rad/s, m/s^2 (at rest the accelerometer reads +g UP)."""
        gyro, accel = np.asarray(gyro, float), np.asarray(accel, float)
        norm = np.linalg.norm(accel)
        if self.r is None:
            if norm < 1e-6:
                return None
            up = accel / norm  # the one rotation that takes the measured "up" to world z, with no yaw of its own
            self.r = rotation(np.cross(up, [0.0, 0.0, 1.0]) / max(np.linalg.norm(np.cross(up, [0.0, 0.0, 1.0])), 1e-9)
                              * math.acos(max(-1.0, min(1.0, up[2]))))
            self.reset_yaw()
            return self.r

        rate = gyro - self.bias
        self.r = self.r @ rotation(rate * dt)
        trusted = abs(norm - GRAVITY) < ACCEL_TRUST
        if trusted:
            # tilt error in the world frame: from where "up" is measured to where it should be
            error = np.cross(self.r @ (accel / norm), [0.0, 0.0, 1.0])
            self.r = rotation(error * ACCEL_GAIN) @ self.r
        self.still_for = self.still_for + dt if trusted and np.linalg.norm(rate) < STILL_RATE else 0.0
        if self.still_for > STILL_S:
            self.bias += BIAS_GAIN * rate  # what the gyro still reads while nothing moves is its bias
        u, _, vt = np.linalg.svd(self.r)   # the products drift off a rotation: back onto one
        self.r = u @ vt
        return self.r
