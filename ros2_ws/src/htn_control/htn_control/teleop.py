import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray

# Finger order for every command: thumb, index, middle, ring, pinky
# Values in radians, 0 = open
COMMAND_TOPIC = '/hand_position_controller/commands'


class Teleop(Node):
    """Manual finger control. TODO: read keyboard/gamepad and publish finger targets."""

    def __init__(self):
        super().__init__('teleop')
        self.command_pub = self.create_publisher(Float64MultiArray, COMMAND_TOPIC, 10)
        self.get_logger().info('teleop node up (stub)')


def main():
    rclpy.init()
    node = Teleop()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
