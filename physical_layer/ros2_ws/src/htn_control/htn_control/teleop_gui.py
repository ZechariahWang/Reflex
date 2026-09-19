import tkinter as tk
from tkinter import ttk

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray

from htn_control.hand_config import FINGERS

COMMAND_TOPIC = '/hand/command'  # normalized: 0 = open, 1 = closed
STATE_TOPIC = '/hand/state'

# One key pair per finger, in FINGERS order: (close, open)
KEYS = [('q', 'a'), ('w', 's'), ('e', 'd'), ('r', 'f'), ('t', 'g')]
TICK_MS = 20
# Keyboard auto-repeat shows up as release+press pairs a few ms apart; a release
# only counts once no press has followed it within this time
RELEASE_DEBOUNCE_MS = 40


class TeleopGui(Node):
    """Hold-to-move control of the five fingers (each is a single open/close DOF).

    While a finger's close/open key is held the finger travels at `speed`;
    letting go holds it where it is. Sliders do the same job with the mouse.
    """

    def __init__(self, root):
        super().__init__('teleop_gui')
        self.root = root
        # Finger travel while a key is held, in full ranges per second
        self.speed = self.declare_parameter('speed', 0.6).value
        self.command_pub = self.create_publisher(Float64MultiArray, COMMAND_TOPIC, 10)
        self.create_subscription(Float64MultiArray, STATE_TOPIC, self.on_state, 10)

        # key -> (finger index, direction)
        self.bindings = {}
        for i, (close_key, open_key) in enumerate(KEYS):
            self.bindings[close_key] = (i, +1.0)
            self.bindings[open_key] = (i, -1.0)
        self.held = set()
        self.pending_release = {}

        root.title('Hand teleop')
        frame = ttk.Frame(root, padding=12)
        frame.grid()
        for column, title in enumerate(['', 'close / open', 'target (0 open .. 1 closed)', 'measured']):
            ttk.Label(frame, text=title).grid(row=0, column=column, padx=6)

        self.targets = []
        self.measured = []
        for i, (name, (close_key, open_key)) in enumerate(zip(FINGERS, KEYS)):
            target = tk.DoubleVar(value=0.0)
            measured = tk.DoubleVar(value=0.0)
            ttk.Label(frame, text=name, width=8).grid(row=i + 1, column=0, sticky='w')
            ttk.Label(frame, text=f'{close_key.upper()} / {open_key.upper()}').grid(row=i + 1, column=1)
            tk.Scale(frame, variable=target, from_=0.0, to=1.0, resolution=0.001,
                     orient='horizontal', length=260).grid(row=i + 1, column=2)
            ttk.Progressbar(frame, variable=measured, maximum=1.0,
                            length=140).grid(row=i + 1, column=3, padx=6)
            self.targets.append(target)
            self.measured.append(measured)

        buttons = ttk.Frame(frame)
        buttons.grid(row=len(FINGERS) + 1, column=0, columnspan=4, pady=(12, 0))
        ttk.Button(buttons, text='Open all', command=lambda: self.set_all(0.0)).grid(row=0, column=0, padx=6)
        ttk.Button(buttons, text='Close all', command=lambda: self.set_all(1.0)).grid(row=0, column=1, padx=6)
        ttk.Label(frame, text='hold a key to move that finger, let go to stop').grid(
            row=len(FINGERS) + 2, column=0, columnspan=4, pady=(8, 0))

        root.bind('<KeyPress>', self.on_key_press)
        root.bind('<KeyRelease>', self.on_key_release)
        # Keys can't be "let go" of once the window loses focus: stop everything
        root.bind('<FocusOut>', lambda _: self.held.clear())
        root.after(TICK_MS, self.tick)

    def set_all(self, value):
        for target in self.targets:
            target.set(value)

    def on_key_press(self, event):
        key = event.keysym.lower()
        if key not in self.bindings:
            return
        pending = self.pending_release.pop(key, None)
        if pending is not None:
            self.root.after_cancel(pending)
        self.held.add(key)

    def on_key_release(self, event):
        key = event.keysym.lower()
        if key in self.held and key not in self.pending_release:
            self.pending_release[key] = self.root.after(
                RELEASE_DEBOUNCE_MS, lambda: self.release(key))

    def release(self, key):
        self.pending_release.pop(key, None)
        self.held.discard(key)

    def on_state(self, msg):
        for measured, value in zip(self.measured, msg.data):
            measured.set(value)

    def tick(self):
        step = self.speed * TICK_MS / 1000.0
        for key in self.held:
            i, direction = self.bindings[key]
            self.targets[i].set(min(max(self.targets[i].get() + direction * step, 0.0), 1.0))

        # Published continuously, so a HAL that (re)starts later still picks up
        # the current targets
        self.command_pub.publish(Float64MultiArray(data=[t.get() for t in self.targets]))
        rclpy.spin_once(self, timeout_sec=0.0)
        if rclpy.ok():
            self.root.after(TICK_MS, self.tick)
        else:
            self.root.destroy()


def main():
    rclpy.init()
    root = tk.Tk()
    node = TeleopGui(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
