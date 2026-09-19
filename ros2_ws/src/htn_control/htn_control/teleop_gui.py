import tkinter as tk
from tkinter import ttk

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray

from htn_control.hand_config import FINGERS

COMMAND_TOPIC = '/hand/command'  # normalized: 0 = open, 1 = closed
STATE_TOPIC = '/hand/state'
NUDGE = 0.1
PUBLISH_PERIOD_MS = 100


class TeleopGui(Node):
    """Window with one slider per finger (each finger is a single open/close DOF).

    Keys work while the window is focused: 1-5 toggle a finger, - / = nudge the
    last selected one, o / c open / close all.
    """

    def __init__(self, root):
        super().__init__('teleop_gui')
        self.root = root
        self.selected = 0
        self.command_pub = self.create_publisher(Float64MultiArray, COMMAND_TOPIC, 10)
        self.create_subscription(Float64MultiArray, STATE_TOPIC, self.on_state, 10)

        root.title('Hand teleop')
        frame = ttk.Frame(root, padding=12)
        frame.grid()
        for column, title in enumerate(['', 'target (0 open .. 1 closed)', '', 'measured']):
            ttk.Label(frame, text=title).grid(row=0, column=column, padx=6)

        self.targets = []
        self.measured = []
        for i, name in enumerate(FINGERS):
            target = tk.DoubleVar(value=0.0)
            measured = tk.DoubleVar(value=0.0)
            ttk.Label(frame, text=f'{i + 1}  {name}', width=10).grid(row=i + 1, column=0, sticky='w')
            tk.Scale(frame, variable=target, from_=0.0, to=1.0, resolution=0.01,
                     orient='horizontal', length=260,
                     command=lambda _, i=i: self.select(i)).grid(row=i + 1, column=1)
            ttk.Button(frame, text='toggle', width=7,
                       command=lambda i=i: self.toggle(i)).grid(row=i + 1, column=2, padx=6)
            ttk.Progressbar(frame, variable=measured, maximum=1.0,
                            length=140).grid(row=i + 1, column=3, padx=6)
            self.targets.append(target)
            self.measured.append(measured)

        buttons = ttk.Frame(frame)
        buttons.grid(row=len(FINGERS) + 1, column=0, columnspan=4, pady=(12, 0))
        ttk.Button(buttons, text='Open all (o)', command=lambda: self.set_all(0.0)).grid(row=0, column=0, padx=6)
        ttk.Button(buttons, text='Close all (c)', command=lambda: self.set_all(1.0)).grid(row=0, column=1, padx=6)
        ttk.Label(frame, text='keys: 1-5 toggle   - / = nudge   o / c all').grid(
            row=len(FINGERS) + 2, column=0, columnspan=4, pady=(8, 0))

        root.bind('<Key>', self.on_key)
        root.after(PUBLISH_PERIOD_MS, self.tick)

    def select(self, i):
        self.selected = i

    def toggle(self, i):
        self.selected = i
        self.targets[i].set(0.0 if self.targets[i].get() > 0.5 else 1.0)

    def nudge(self, step):
        target = self.targets[self.selected]
        target.set(min(max(target.get() + step, 0.0), 1.0))

    def set_all(self, value):
        for target in self.targets:
            target.set(value)

    def on_key(self, event):
        key = event.char
        if key and key in '12345':
            self.toggle(int(key) - 1)
        elif key == '=':
            self.nudge(NUDGE)
        elif key == '-':
            self.nudge(-NUDGE)
        elif key == 'o':
            self.set_all(0.0)
        elif key == 'c':
            self.set_all(1.0)

    def on_state(self, msg):
        for measured, value in zip(self.measured, msg.data):
            measured.set(value)

    def tick(self):
        # Republish continuously so a HAL that (re)starts later still picks up
        # the current targets
        self.command_pub.publish(Float64MultiArray(data=[t.get() for t in self.targets]))
        rclpy.spin_once(self, timeout_sec=0.0)
        if rclpy.ok():
            self.root.after(PUBLISH_PERIOD_MS, self.tick)
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
