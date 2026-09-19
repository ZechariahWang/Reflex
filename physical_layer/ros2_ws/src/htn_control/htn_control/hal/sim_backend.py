from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray

from htn_control.hal.base import HandBackend
from htn_control.hand_config import FINGERS


# gz_ros2_control turns a position command into a joint velocity,
# gain * error * update_rate, with gain = 0.1 at 100 Hz: every simulated servo is
# a first-order lag of about 100 ms behind its command (0.085 tracks best: measured). The gain cannot be
# raised: release 0.7.x creates its node before it loads the parameter file, so
# position_proportional_gain never reaches it (the log always says "set to: 0.1").
SERVO_LAG_S = 0.085
# While a finger brakes into the end of its travel, the leading command has to sit a little
# beyond that end (by up to max_accel * lag^2 / 2 of the range), or the finger crawls the last
# tenth on Gazebo's lag alone. This is a command, not a position: the lead is zero whenever
# the setpoint rests, so the joint never comes to rest out there (the DART limit trap).
LEAD_BEYOND_RANGE = 0.12


class SimBackend(HandBackend):
    """Gazebo: talks to the ros2_control position controller, in radians.

    The command leads the setpoint by SERVO_LAG_S * its velocity, which is
    exactly what a first-order lag loses, so the simulated finger tracks the
    HAL's ramp instead of trailing it by 100 ms.
    """

    publishes_joint_states = True  # joint_state_broadcaster does it

    def __init__(self, node, hand_params):
        super().__init__(node, hand_params)
        fingers = hand_params['fingers']
        self.lower = [fingers[f]['min_angle'] for f in FINGERS]
        self.upper = [fingers[f]['max_angle'] for f in FINGERS]
        self.joint_names = [f + '_joint' for f in FINGERS]
        self.measured = None
        self.previous = None  # (positions, time) of the last write

        self.command_pub = node.create_publisher(
            Float64MultiArray, '/hand_position_controller/commands', 10)
        node.create_subscription(JointState, '/joint_states', self.on_joint_states, 10)

    def write(self, positions):
        now = self.node.get_clock().now().nanoseconds * 1e-9
        lead = [0.0] * len(positions)
        if self.previous is not None and now > self.previous[1]:
            dt = now - self.previous[1]
            lead = [SERVO_LAG_S * (p - q) / dt for p, q in zip(positions, self.previous[0])]
        self.previous = (list(positions), now)
        angles = [lo + min(max(p + ahead, -LEAD_BEYOND_RANGE), 1.0 + LEAD_BEYOND_RANGE) * (hi - lo)
                  for p, ahead, lo, hi in zip(positions, lead, self.lower, self.upper)]
        self.command_pub.publish(Float64MultiArray(data=angles))

    def read(self):
        return self.measured

    def on_joint_states(self, msg):
        angle = dict(zip(msg.name, msg.position))
        if not all(j in angle for j in self.joint_names):
            return
        self.measured = [(angle[j] - lo) / (hi - lo)
                         for j, lo, hi in zip(self.joint_names, self.lower, self.upper)]
