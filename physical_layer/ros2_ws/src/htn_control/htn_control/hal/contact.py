"""Contact stop: a finger that meets resistance must stop pushing hard.

Pure logic, no ROS (design: docs/specs/hal-safety-design.md, contact-stop-release-design.md).
It protects the linkage - wrong calibration, a jam, the open stop - and it sets the grip force
on an object. One detector per finger; everything is in normalized finger travel (0 = open ..
1 = closed) and HAL cycles.

    free     the setpoint sweeps to the target, the servo has its full torque limit
    blocked  the setpoint sits just past the furthest position the finger reached, in the direction
             it was pushing, and the servo gets the low holding torque: it keeps pushing, softly

Blocked = too much motor current (the measured torque): each cycle adds the mA above
blocked_current to a sum, a cycle below it takes its shortfall off again, and the sum reaching
blocked_excess is the block. One huge cycle does it, so do some cycles a little over; the short
peak of a start drains away. The encoder cannot say it: a resisted finger keeps its speed (the
servo pushes through), and a slow servo trails its setpoint in free motion too.

Free again = the command goes to the other side of the finger, or the finger has travelled
release_travel past where it got blocked (the obstacle is gone, or the block was false). The
current cannot say that: on the holding torque it is low on purpose.
"""
FREE, BLOCKED = 'free', 'blocked'


class ContactDetector:

    def __init__(self, hold_lead, release_travel, blocked_current, blocked_excess=150):
        self.blocked_current = blocked_current  # mA above which a cycle counts
        self.blocked_excess = blocked_excess    # summed mA above it (over cycles) that mean "it meets resistance"
        self.hold_lead = hold_lead              # how far past the finger the setpoint sits while blocked
        # Travel past the block that frees the finger. More than it coasts after the torque drops:
        # at speed it covers 0.04 per cycle, and a release that its momentum meets is no block at all
        self.release_travel = release_travel
        self.reset()

    def reset(self):
        """Forget everything: after passive mode, or when the pose was adopted afresh."""
        self.excess = 0.0
        self.state = FREE
        self.direction = 0.0    # +1 it was closing when it got blocked, -1 opening
        self.blocked_at = None  # measured position when it got blocked
        self.furthest = None    # ... and the furthest it got since, in that direction

    def hold_setpoint(self):
        """Where the setpoint is while blocked. It follows the finger forward and never goes back:
        behind a finger that coasted on, it would pull the finger off the object."""
        return self.furthest + self.direction * self.hold_lead

    def update(self, setpoint, measured, target, current=None):
        """One HAL cycle. Returns the state; read `hold_setpoint()` while it is BLOCKED."""
        if self.state == BLOCKED:
            if (measured - self.furthest) * self.direction > 0:
                self.furthest = measured
            wants_other_way = (target - measured) * self.direction < 0
            travelled_on = (measured - self.blocked_at) * self.direction > self.release_travel
            if wants_other_way or travelled_on:
                self.reset()
            return self.state

        if current is not None:
            self.excess = max(0.0, self.excess + current - self.blocked_current)
        pushing = setpoint - measured or target - measured  # which way: the setpoint leads the finger, else the target
        if pushing and self.excess >= self.blocked_excess:
            self.reset()
            self.state, self.direction = BLOCKED, (1.0 if pushing > 0 else -1.0)
            self.blocked_at = self.furthest = measured
        return self.state
