import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray

# Finger order for every command: thumb, index, middle, ring, pinky
# Values in radians, 0 = open
COMMAND_TOPIC = '/hand_position_controller/commands'


class Auto(Node):
    """Autonomous finger control. TODO: subscribe to cameras/IMU, query the policy, publish finger targets."""

    def __init__(self):
        super().__init__('auto')
        self.command_pub = self.create_publisher(Float64MultiArray, COMMAND_TOPIC, 10)
        self.get_logger().info('auto node up (stub)')


def main():
    rclpy.init()
    node = Auto()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
