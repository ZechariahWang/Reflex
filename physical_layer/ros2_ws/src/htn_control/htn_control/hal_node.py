import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray

from htn_control.hal import BACKENDS
from htn_control.hand_config import FINGERS, load_hand_params

COMMAND_TOPIC = '/hand/command'  # Float64MultiArray, 5 x [0..1], FINGERS order
STATE_TOPIC = '/hand/state'      # same layout, measured (or commanded if unknown)


class HandHal(Node):
    """Hardware abstraction layer for the hand.

    Teleop and the autonomous node only ever publish normalized finger
    positions on /hand/command; this node clamps and rate-limits them and
    hands them to whichever backend is selected (sim | feetech).
    """

    def __init__(self):
        super().__init__('hand_hal')
        backend_name = self.declare_parameter('backend', 'sim').value
        params_file = self.declare_parameter('params_file', '').value
        rate = self.declare_parameter('rate', 50.0).value
        # Fastest a finger may travel, in full ranges per second
        self.max_speed = self.declare_parameter('max_speed', 2.0).value

        self.hand_params = load_hand_params(params_file)
        if backend_name not in BACKENDS:
            raise ValueError(f"backend must be one of {list(BACKENDS)}, got '{backend_name}'")
        self.backend = BACKENDS[backend_name](self, self.hand_params)

        self.dt = 1.0 / rate
        self.target = [0.0] * len(FINGERS)
        self.setpoint = [0.0] * len(FINGERS)

        self.create_subscription(Float64MultiArray, COMMAND_TOPIC, self.on_command, 10)
        self.state_pub = self.create_publisher(Float64MultiArray, STATE_TOPIC, 10)
        self.joint_state_pub = None
        if not self.backend.publishes_joint_states:
            self.joint_state_pub = self.create_publisher(JointState, '/joint_states', 10)
        self.create_timer(self.dt, self.update)
        self.get_logger().info(f"Hand HAL up, backend '{backend_name}'")

    def on_command(self, msg):
        if len(msg.data) != len(FINGERS):
            self.get_logger().warning(
                f'Ignoring command with {len(msg.data)} values, expected {len(FINGERS)}',
                throttle_duration_sec=2.0)
            return
        self.target = [min(max(v, 0.0), 1.0) for v in msg.data]

    def update(self):
        max_step = self.max_speed * self.dt
        self.setpoint = [s + min(max(t - s, -max_step), max_step)
                         for s, t in zip(self.setpoint, self.target)]
        self.backend.write(self.setpoint)

        state = self.backend.read() or self.setpoint
        self.state_pub.publish(Float64MultiArray(data=state))
        if self.joint_state_pub is not None:
            self.publish_joint_states(state)

    def publish_joint_states(self, state):
        fingers = self.hand_params['fingers']
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = [f + '_joint' for f in FINGERS]
        msg.position = [
            fingers[f]['min_angle'] + p * (fingers[f]['max_angle'] - fingers[f]['min_angle'])
            for f, p in zip(FINGERS, state)]
        self.joint_state_pub.publish(msg)


def main():
    rclpy.init()
    node = HandHal()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.backend.close()
        node.destroy_node()
        rclpy.try_shutdown()
