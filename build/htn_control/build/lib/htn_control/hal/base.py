from abc import ABC, abstractmethod


class HandBackend(ABC):
    """One way of actually moving the fingers (simulator, serial servos, ...).

    Everything crossing this interface is a list of 5 floats in FINGERS order,
    normalized: 0.0 = finger fully open, 1.0 = fully closed. Turning that into
    radians, servo degrees, PWM... is the backend's job, so nothing above the
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

    def close(self):
        """Release the device. Called once on shutdown."""
