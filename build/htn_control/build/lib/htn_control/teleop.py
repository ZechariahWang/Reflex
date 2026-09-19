import select
import sys
import termios
import tty

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray

from htn_control.hand_config import FINGERS

COMMAND_TOPIC = '/hand/command'  # normalized: 0 = open, 1 = closed
NUDGE = 0.1

HELP = """
Hand teleop
  1 2 3 4 5 : toggle thumb / index / middle / ring / pinky (open <-> closed)
  - / =     : nudge the last selected finger open / closed
  o / c     : open all / close all
  q         : quit
"""


class Teleop(Node):
    """Keyboard control of the five fingers (each is a single open/close DOF)."""

    def __init__(self):
        super().__init__('teleop')
        self.command_pub = self.create_publisher(Float64MultiArray, COMMAND_TOPIC, 10)
        self.targets = [0.0] * len(FINGERS)
        self.selected = 0

    def handle_key(self, key):
        """Returns False when the user wants to quit."""
        if key in '12345':
            self.selected = int(key) - 1
            self.targets[self.selected] = 0.0 if self.targets[self.selected] > 0.5 else 1.0
        elif key in '-=':
            step = NUDGE if key == '=' else -NUDGE
            self.targets[self.selected] = min(max(self.targets[self.selected] + step, 0.0), 1.0)
        elif key == 'o':
            self.targets = [0.0] * len(FINGERS)
        elif key == 'c':
            self.targets = [1.0] * len(FINGERS)
        elif key in ('q', '\x03'):
            return False
        return True

    def publish(self):
        self.command_pub.publish(Float64MultiArray(data=self.targets))

    def status(self):
        return '  '.join(
            f"{'>' if i == self.selected else ' '}{name} {target:.1f}"
            for i, (name, target) in enumerate(zip(FINGERS, self.targets)))


def main():
    if not sys.stdin.isatty():
        sys.exit('teleop needs a keyboard: run it in its own terminal with '
                 '`ros2 run htn_control teleop`')

    rclpy.init()
    node = Teleop()
    print(HELP)
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        running = True
        while running and rclpy.ok():
            # Republish at 10 Hz even without key presses, so a HAL that
            # (re)starts later still picks up the current targets
            if select.select([sys.stdin], [], [], 0.1)[0]:
                running = node.handle_key(sys.stdin.read(1))
            node.publish()
            print('\r' + node.status(), end='', flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        print()
        node.destroy_node()
        rclpy.try_shutdown()
