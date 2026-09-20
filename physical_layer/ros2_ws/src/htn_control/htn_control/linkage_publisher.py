import math

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import JointState

from htn_control.hand_config import FINGERS, load_hand_params, load_linkage
from htn_control.linkage import PASSIVE, Linkage, PassiveJoints

# The linkage must not be driven close to where it binds: there the pad barely
# moves any more and the pins take the whole servo torque
LOCK_MARGIN = math.radians(5.0)
# Of the driven-joint messages (100 Hz in sim) every Nth gets the full hand published next to
# it: 50 Hz is plenty for TF, and (de)serializing 35 joints per message is what costs in rclpy.
EVERY_NTH = 2


class LinkagePublisher(Node):
    """Closes the loops of the finger linkages for everything that draws the hand.

    The URDF is a tree; only <finger>_joint (the servo horn) is driven, by the
    simulation or the HAL. This node listens for those on /joint_states and
    publishes the six passive joints of each finger, so robot_state_publisher
    (and any viewer that reads /joint_states) shows the mechanism as it really
    moves.

    Its message REPEATS the driven joints. It goes out right after every
    driven-joint message, so a subscriber that keeps only the latest message
    per period - rosbridge with throttle_rate, which is how the web console
    listens - would otherwise see almost nothing but passive joints: the 3D
    hand then got two horn updates per move and jumped through one
    intermediate pose.
    """

    def __init__(self):
        super().__init__('linkage_publisher')
        params = load_hand_params(self.declare_parameter('params_file', '').value)
        linkage = load_linkage(self.declare_parameter('linkage_file', '').value)

        self.driven = [f + '_joint' for f in FINGERS]
        self.names = [f'{f}_{role}_joint' for f in FINGERS for role in PASSIVE]
        self.solvers = []
        for finger in FINGERS:
            geometry, closed = linkage[finger], params['fingers'][finger]['max_angle']
            opened = params['fingers'][finger]['min_angle']
            if closed > geometry['lock_rad'] - LOCK_MARGIN:
                raise ValueError(
                    f"{finger}: max_angle {closed:.3f} rad is within {math.degrees(LOCK_MARGIN):.0f} deg of "
                    f"where the linkage binds ({geometry['lock_rad']:.3f} rad). Lower it in hand_params.yaml")
            if -opened > geometry['open_lock_rad'] - LOCK_MARGIN:
                raise ValueError(
                    f"{finger}: min_angle {opened:.3f} rad is within {math.degrees(LOCK_MARGIN):.0f} deg of "
                    f"where the linkage binds when it opens (-{geometry['open_lock_rad']:.3f} rad). "
                    'Raise it in hand_params.yaml')
            self.solvers.append(PassiveJoints(Linkage(geometry['pivots'], geometry['closing']), closed, opened=opened))

        self.publisher = self.create_publisher(JointState, '/joint_states', 10)
        # Raw: half of what arrives is our own output, and a byte search turns that away without
        # deserializing it (which alone was a quarter of a core)
        self.own_marker = self.names[0].encode()
        self.count = 0
        self.create_subscription(JointState, '/joint_states', self.on_raw, 10, raw=True)
        self.get_logger().info(f'Linkage publisher up: {len(self.names)} passive joints')

    def on_raw(self, data):
        if self.own_marker in data:
            return
        self.count += 1
        if self.count % EVERY_NTH:
            return
        out = self.complete(deserialize_message(data, JointState))
        if out is not None:
            self.publisher.publish(out)

    def complete(self, msg):
        """The whole hand for a message that carries the driven joints, else None."""
        # Half of what arrives here is our own output: turn that away before doing any work
        if len(msg.name) > len(self.driven) and self.names[0] in msg.name:
            return None
        angle = dict(zip(msg.name, msg.position))
        if not all(joint in angle for joint in self.driven):
            return None  # somebody else's joints
        out = JointState()
        out.header.stamp = msg.header.stamp  # same instant as the horns: no tearing in TF
        out.name = self.driven + self.names
        out.position = [angle[joint] for joint in self.driven] + [
            a for joint, solver in zip(self.driven, self.solvers) for a in solver(angle[joint])]
        return out


def main():
    rclpy.init()
    node = LinkagePublisher()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
