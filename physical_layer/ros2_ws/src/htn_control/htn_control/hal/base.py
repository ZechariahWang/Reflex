from abc import ABC, abstractmethod


class HandBackend(ABC):
    """One way of actually moving the fingers (simulator, bus servos, ...).

    Everything crossing this interface is a list of 5 floats in FINGERS order,
    normalized: 0.0 = finger fully open, 1.0 = fully closed. Turning that into
    radians, servo steps, PWM... is the backend's job, so nothing above the
    HAL ever needs to know what hardware it is talking to.
    """

    # True if something else already publishes /joint_states for this backend
    publishes_joint_states = False

    def __init__(self, node, hand_params):
        self.node = node
        self.hand_params = hand_params

    @abstractmethod
    def write(self, positions):
        """Send target finger positions (normalized)."""

    @abstractmethod
    def read(self):
        """Return measured finger positions (normalized), or None if unknown."""

    def set_torque(self, enabled, hold=None):
        """Power the motors, or release them so the fingers can be moved by hand.

        The HAL calls this with False when it enters passive (backdrive) mode
        and with True when it leaves it. `hold` is then the measured pose
        (normalized): the backend must make it the goal BEFORE the torque comes
        back, or the hand snaps to wherever it was last commanded.
        Default: nothing to do (the simulated hand cannot be pushed around).
        """

    def close(self):
        """Release the device. Called once on shutdown."""
