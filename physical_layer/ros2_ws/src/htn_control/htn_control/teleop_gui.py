import tkinter as tk
from tkinter import ttk

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray

from htn_control.hand_config import FINGERS
from htn_control.poses import POSES, SEQUENCES, resolve

COMMAND_TOPIC = '/hand/command'  # normalized: 0 = open, 1 = closed
STATE_TOPIC = '/hand/state'

# One key pair per finger, in FINGERS order: (close, open)
KEYS = [('a', 'q'), ('s', 'w'), ('d', 'e'), ('f', 'r'), ('g', 't')]
TICK_MS = 20
# Keyboard auto-repeat shows up as release+press pairs a few ms apart; a release
# only counts once no press has followed it within this time
RELEASE_DEBOUNCE_MS = 40
POSE_BUTTONS_PER_ROW = 5
# Targets closer than this to the last command on the topic are not republished
COMMAND_TOLERANCE = 0.002


class TeleopGui(Node):
    """Hold-to-move control of the five fingers (each is a single open/close DOF).

    While a finger's close/open key is held the finger travels at `speed`;
    letting go holds it where it is. Sliders do the same job with the mouse.
    Pose / sequence buttons run the pre-written movements from poses.py; clicking
    the active one again goes back to open.

    Only publishes when the user changes something here. /hand/command is shared
    with other sources (web app, autonomous node): their commands are adopted
    into the sliders instead of being overwritten.
    """

    def __init__(self, root):
        super().__init__('teleop_gui')
        self.root = root
        # Finger travel while a key is held, in full ranges per second
        self.speed = self.declare_parameter('speed', 0.6).value
        self.command_pub = self.create_publisher(Float64MultiArray, COMMAND_TOPIC, 10)
        self.create_subscription(Float64MultiArray, STATE_TOPIC, self.on_state, 10)
        self.create_subscription(Float64MultiArray, COMMAND_TOPIC, self.on_command, 10)
        # Last command seen on the topic, ours or anyone else's
        self.last_command = [0.0] * len(FINGERS)

        # key -> (finger index, direction)
        self.bindings = {}
        for i, (close_key, open_key) in enumerate(KEYS):
            self.bindings[close_key] = (i, +1.0)
            self.bindings[open_key] = (i, -1.0)
        self.held = set()
        self.pending_release = {}
        self.active = None          # name of the pose / sequence in effect
        self.sequence_timer = None

        root.title('Hand teleop')
        frame = ttk.Frame(root, padding=12)
        frame.grid()
        for column, title in enumerate(['', 'open / close', 'target (0 open .. 1 closed)', 'measured']):
            ttk.Label(frame, text=title).grid(row=0, column=column, padx=6)

        self.targets = []
        self.measured = []
        for i, (name, (close_key, open_key)) in enumerate(zip(FINGERS, KEYS)):
            target = tk.DoubleVar(value=0.0)
            measured = tk.DoubleVar(value=0.0)
            ttk.Label(frame, text=name, width=8).grid(row=i + 1, column=0, sticky='w')
            ttk.Label(frame, text=f'{open_key.upper()} / {close_key.upper()}').grid(row=i + 1, column=1)
            tk.Scale(frame, variable=target, from_=0.0, to=1.0, resolution=0.001,
                     orient='horizontal', length=260).grid(row=i + 1, column=2)
            ttk.Progressbar(frame, variable=measured, maximum=1.0,
                            length=140).grid(row=i + 1, column=3, padx=6)
            self.targets.append(target)
            self.measured.append(measured)

        ttk.Label(frame, text='hold a key to move that finger, let go to stop').grid(
            row=len(FINGERS) + 1, column=0, columnspan=4, pady=(8, 0))

        self.buttons = {}
        self.add_buttons(frame, len(FINGERS) + 2, 'Poses', POSES, self.toggle_pose)
        self.add_buttons(frame, len(FINGERS) + 3, 'Sequences', SEQUENCES, self.toggle_sequence)

        root.bind('<KeyPress>', self.on_key_press)
        root.bind('<KeyRelease>', self.on_key_release)
        # Keys can't be "let go" of once the window loses focus: stop everything
        root.bind('<FocusOut>', lambda _: self.held.clear())
        root.after(TICK_MS, self.tick)

    def add_buttons(self, parent, row, title, names, callback):
        box = ttk.LabelFrame(parent, text=title, padding=6)
        box.grid(row=row, column=0, columnspan=4, sticky='ew', pady=(10, 0))
        for n, name in enumerate(names):
            button = tk.Button(box, text=name, width=11,
                               command=lambda name=name: callback(name))
            button.grid(row=n // POSE_BUTTONS_PER_ROW, column=n % POSE_BUTTONS_PER_ROW,
                        padx=3, pady=3)
            self.buttons[name] = button

    def set_targets(self, values):
        for target, value in zip(self.targets, values):
            target.set(value)

    def set_active(self, name):
        if self.sequence_timer is not None:
            self.root.after_cancel(self.sequence_timer)
            self.sequence_timer = None
        self.active = name
        for button_name, button in self.buttons.items():
            button.config(relief='sunken' if button_name == name else 'raised')

    def toggle_pose(self, name):
        if self.active == name:
            name = 'open'
        self.set_active(name)
        self.set_targets(POSES[name])

    def toggle_sequence(self, name):
        if self.active == name:
            self.toggle_pose('open')
            return
        self.set_active(name)
        self.run_sequence(name, 0)

    def run_sequence(self, name, step):
        self.sequence_timer = None
        pose, seconds = SEQUENCES[name][step]
        self.set_targets(resolve(pose))
        if step + 1 < len(SEQUENCES[name]):
            self.sequence_timer = self.root.after(
                int(seconds * 1000), lambda: self.run_sequence(name, step + 1))
        else:
            self.set_active(None)

    def on_key_press(self, event):
        key = event.keysym.lower()
        if key not in self.bindings:
            return
        pending = self.pending_release.pop(key, None)
        if pending is not None:
            self.root.after_cancel(pending)
        self.held.add(key)
        self.set_active(None)  # manual control takes over from poses / sequences

    def on_key_release(self, event):
        key = event.keysym.lower()
        if key in self.held and key not in self.pending_release:
            self.pending_release[key] = self.root.after(
                RELEASE_DEBOUNCE_MS, lambda: self.release(key))

    def release(self, key):
        self.pending_release.pop(key, None)
        self.held.discard(key)

    def differs(self, values):
        return any(abs(a - b) > COMMAND_TOLERANCE for a, b in zip(values, self.last_command))

    def on_command(self, msg):
        values = list(msg.data)
        if len(values) != len(FINGERS) or not self.differs(values):
            return  # malformed, or our own message coming back
        # Someone else is driving: follow them rather than fight them
        self.last_command = values
        if not self.held:
            self.set_active(None)
            self.set_targets(values)

    def on_state(self, msg):
        for measured, value in zip(self.measured, msg.data):
            measured.set(value)

    def tick(self):
        step = self.speed * TICK_MS / 1000.0
        for key in self.held:
            i, direction = self.bindings[key]
            self.targets[i].set(min(max(self.targets[i].get() + direction * step, 0.0), 1.0))

        targets = [t.get() for t in self.targets]
        # A slider dragged away from the active pose: it no longer applies
        if self.active in POSES and targets != POSES[self.active]:
            self.set_active(None)

        if self.differs(targets):
            self.last_command = targets
            self.command_pub.publish(Float64MultiArray(data=targets))
        for _ in range(10):  # state + command both arrive faster than we tick
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
