"""Contact stop: a finger that has to move and does not must stop pushing hard.

Pure logic, no ROS (design: docs/specs/hal-safety-design.md). It protects the
linkage - wrong calibration, a jam, the open stop - and it sets the grip force
on an object. One detector per finger; everything is in normalized finger
travel (0 = open .. 1 = closed) and HAL cycles.

    free     the setpoint sweeps to the target, the servo has its full torque limit
    blocked  the setpoint is frozen just past the measured position, in the direction the
             finger was pushing, and the servo gets the low holding torque

Blocked = the motor current stays above blocked_current (the measured torque: it
works next to the target and on something soft, where the encoder rule is blind),
OR far from the setpoint AND not moving. Not the distance alone: a slow servo
(low torque limit) trails its setpoint in free motion too. A backend without a
current reading has the encoder rule only.
"""
from collections import deque

FREE, BLOCKED = 'free', 'blocked'


class ContactDetector:

    def __init__(self, blocked_error, blocked_motion, blocked_cycles, hold_lead,
                 blocked_current=None, current_cycles=5):
        self.blocked_current = blocked_current  # mA that mean "it meets resistance", None = not used
        self.current_cycles = current_cycles    # ... for this many cycles in a row: a start-up peak is shorter
        self.over_current = 0
        self.blocked_error = blocked_error    # |setpoint - measured| that means "has to move"
        self.blocked_motion = blocked_motion  # travel over blocked_cycles below which it "does not"
        self.hold_lead = hold_lead            # how far past the measured position the frozen setpoint sits
        self.history = deque(maxlen=blocked_cycles + 1)
        self.state = FREE
        self.direction = 0.0   # +1 it was closing when it got blocked, -1 opening
        self.held_at = None    # measured position when it got blocked

    def reset(self):
        """Forget everything: after passive mode, or when the pose was adopted afresh."""
        self.history.clear()
        self.over_current = 0
        self.state, self.direction, self.held_at = FREE, 0.0, None

    def hold_setpoint(self):
        """Where the setpoint stays while blocked."""
        return self.held_at + self.direction * self.hold_lead

    def update(self, setpoint, measured, target, current=None):
        """One HAL cycle. Returns the state; read `hold_setpoint()` while it is BLOCKED."""
        self.history.append(measured)
        if self.state == BLOCKED:
            wants_other_way = (target - measured) * self.direction < 0
            # With the setpoint only hold_lead ahead, a finger that gets there was let go
            moves_again = (measured - self.held_at) * self.direction > self.hold_lead / 2
            if wants_other_way or moves_again:
                self.reset()
            return self.state

        error = setpoint - measured
        pushing = error or target - measured  # which way: the setpoint leads the finger, else the target
        over = self.blocked_current is not None and current is not None and current >= self.blocked_current
        self.over_current = self.over_current + 1 if over else 0
        stuck = (abs(error) > self.blocked_error and len(self.history) == self.history.maxlen
                 and abs(self.history[-1] - self.history[0]) < self.blocked_motion)
        if pushing and (stuck or self.over_current >= self.current_cycles):
            self.state, self.direction, self.held_at = BLOCKED, (1.0 if pushing > 0 else -1.0), measured
            self.history.clear()
            self.over_current = 0
        return self.state
