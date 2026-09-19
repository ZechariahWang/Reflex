import select
import sys
import termios
import tty

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray

from htn_control.hand_config import FINGERS

COMMAND_TOPIC = '/hand/command'  # normalized: 0 = open, 1 = closed
# One key pair per finger, in FINGERS order: (close, open)
KEYS = [('a', 'q'), ('s', 'w'), ('d', 'e'), ('f', 'r'), ('g', 't')]
# A terminal can't see key releases, only the characters auto-repeat produces
# while a key is held: every character moves the finger one small step.
STEP = 0.03

HELP = """
Hand teleop - hold a key to move a finger, let go to stop
  open:   q thumb   w index   e middle   r ring   t pinky
  close:  a thumb   s index   d middle   f ring   g pinky
  x: quit
"""


class Teleop(Node):
    """Keyboard control of the five fingers (each is a single open/close DOF)."""

    def __init__(self):
        super().__init__('teleop')
        self.command_pub = self.create_publisher(Float64MultiArray, COMMAND_TOPIC, 10)
        self.targets = [0.0] * len(FINGERS)
        # key -> (finger index, direction)
        self.bindings = {}
        for i, (close_key, open_key) in enumerate(KEYS):
            self.bindings[close_key] = (i, +STEP)
            self.bindings[open_key] = (i, -STEP)

    def handle_key(self, key):
        """Returns False when the user wants to quit."""
        if key in ('x', '\x03'):
            return False
        if key.lower() in self.bindings:
            i, step = self.bindings[key.lower()]
            self.targets[i] = min(max(self.targets[i] + step, 0.0), 1.0)
        return True

    def publish(self):
        self.command_pub.publish(Float64MultiArray(data=self.targets))

    def status(self):
        return '  '.join(f'{name} {target:.2f}' for name, target in zip(FINGERS, self.targets))


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
