from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray

from htn_control.hal.base import HandBackend
from htn_control.hand_config import FINGERS


class SimBackend(HandBackend):
    """Gazebo: talks to the ros2_control position controller, in radians."""

    publishes_joint_states = True  # joint_state_broadcaster does it

    def __init__(self, node, hand_params):
        super().__init__(node, hand_params)
        fingers = hand_params['fingers']
        self.lower = [fingers[f]['min_angle'] for f in FINGERS]
        self.upper = [fingers[f]['max_angle'] for f in FINGERS]
        self.joint_names = [f + '_joint' for f in FINGERS]
        self.measured = None

        self.command_pub = node.create_publisher(
            Float64MultiArray, '/hand_position_controller/commands', 10)
        node.create_subscription(JointState, '/joint_states', self.on_joint_states, 10)

    def write(self, positions):
        angles = [lo + p * (hi - lo)
                  for p, lo, hi in zip(positions, self.lower, self.upper)]
        self.command_pub.publish(Float64MultiArray(data=angles))

    def read(self):
        return self.measured

    def on_joint_states(self, msg):
        angle = dict(zip(msg.name, msg.position))
        if not all(j in angle for j in self.joint_names):
            return
        self.measured = [(angle[j] - lo) / (hi - lo)
                         for j, lo, hi in zip(self.joint_names, self.lower, self.upper)]
