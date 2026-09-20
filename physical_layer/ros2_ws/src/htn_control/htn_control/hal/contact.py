"""Contact stop: a finger that has to move and does not must stop pushing hard.

Pure logic, no ROS (design: docs/specs/hal-safety-design.md). It protects the
linkage - wrong calibration, a jam, the open stop - and it sets the grip force
on an object. One detector per finger; everything is in normalized finger
travel (0 = open .. 1 = closed) and HAL cycles.

    free     the setpoint sweeps to the target, the servo has its full torque limit
    blocked  the setpoint is frozen just past the measured position, in the direction the
             finger was pushing, and the servo gets the low holding torque

Blocked = too much motor current (the measured torque: it works next to the target
and on something soft, where the encoder rule is blind): each cycle adds the mA above
blocked_current to a sum, a cycle below it takes its shortfall off again, and the sum
reaching blocked_excess is the block. One huge cycle does it, so do some cycles a little
over; the short peak of a start drains away.
OR far from the setpoint AND not moving. Not the distance alone: a slow servo
(low torque limit) trails its setpoint in free motion too. A backend without a
current reading has the encoder rule only.
"""
from collections import deque

FREE, BLOCKED = 'free', 'blocked'


class ContactDetector:

    def __init__(self, blocked_error, blocked_motion, blocked_cycles, hold_lead,
                 blocked_current=None, blocked_excess=150):
        self.blocked_current = blocked_current  # mA above which a cycle counts, None = not used
        self.blocked_excess = blocked_excess    # summed mA above it (over cycles) that mean "it meets resistance"
        self.excess = 0.0
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
        self.excess = 0.0
        self.state, self.direction, self.held_at = FREE, 0.0, None

    def hold_setpoint(self):
        """Where the setpoint stays while blocked."""
        return self.held_at + self.direction * self.hold_lead

    def update(self, setpoint, measured, target, current=None):
        """One HAL cycle. Returns the state; read `hold_setpoint()` while it is BLOCKED."""
        if self.state == BLOCKED:
            wants_other_way = (target - measured) * self.direction < 0
            # With the setpoint only hold_lead ahead, a finger that gets there was let go
            moves_again = (measured - self.held_at) * self.direction > self.hold_lead / 2
            if wants_other_way or moves_again:
                self.reset()
            return self.state

        error = setpoint - measured
        # The window of "does not move" holds only cycles in which the finger HAS to move. With the
        # cycles of the rest before a command in it, every quick start was "far from the setpoint
        # and has not moved for 0.2 s" at once: blocked, low torque, a crawl (seen on the hand).
        if abs(error) > self.blocked_error:
            self.history.append(measured)
        else:
            self.history.clear()
        pushing = error or target - measured  # which way: the setpoint leads the finger, else the target
        if self.blocked_current is not None and current is not None:
            self.excess = max(0.0, self.excess + current - self.blocked_current)
        # max - min, not last - first: a finger that turns around comes back to where the window
        # began, and that is a movement too
        stuck = (len(self.history) == self.history.maxlen
                 and max(self.history) - min(self.history) < self.blocked_motion)
        if pushing and (stuck or (self.excess and self.excess >= self.blocked_excess)):
            self.state, self.direction, self.held_at = BLOCKED, (1.0 if pushing > 0 else -1.0), measured
            self.history.clear()
            self.excess = 0.0
        return self.state
