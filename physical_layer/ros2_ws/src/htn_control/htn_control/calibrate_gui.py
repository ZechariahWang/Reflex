"""Calibration window for the real hand: set each finger's OPEN and CLOSED position.

    ros2 run htn_control servo_tool calibrate

Pick a finger, move it, "Set OPEN"; move it, "Set CLOSED"; Save. Nothing else.
`Calibrator` is the logic (no tkinter, tested on the fake servo bus);
`CalibrateWindow` only draws it.
"""
import math
from collections import deque

from htn_control.hal import feetech
from htn_control.hal.feetech import FeetechError, from_u16, u16
from htn_control.hand_config import FINGERS

STEPS_PER_RAD = 4096 / (2 * math.pi)
LOCK_MARGIN_STEPS = round(math.radians(8.0) * STEPS_PER_RAD)  # as linkage_publisher's LOCK_MARGIN
TEST_STEPS_PER_TICK = 6  # at TICK_MS: ~13 deg of horn per second
TICK_MS = 40
BLOCKED_ERROR_STEPS = 90   # the goal is this far ahead ...
BLOCKED_TICKS = 12         # ... and the servo moved less than BLOCKED_MOTION_STEPS in this many ticks
BLOCKED_MOTION_STEPS = 4


class Calibrator:
    """One finger is active at a time and only that one has torque (a low one)."""

    def __init__(self, bus, params, linkage, torque=150):
        self.bus, self.params, self.linkage, self.torque = bus, params, linkage, torque
        self.ids = {finger: params['servos'][finger]['id'] for finger in FINGERS}
        self.present = {finger: bus.ping(self.ids[finger]) for finger in FINGERS}
        self.open = {}      # finger -> step, set in this session
        self.closed = {}
        self.active = None
        self.goal = None
        self.testing = False
        self.message = 'Pick a finger.'
        self._test = None   # (waypoints left, recent positions)

    def positions(self):
        ids = [self.ids[f] for f in FINGERS if self.present[f]]
        replies = self.bus.sync_read(feetech.ADDR_PRESENT_POSITION, 2, ids) if ids else {}
        return {f: from_u16(replies[self.ids[f]]) if self.ids[f] in replies else None for f in FINGERS}

    def saved(self, finger):
        servo = self.params['servos'][finger]
        return servo['open_step'], servo['closed_step']

    def select(self, finger):
        if not self.present[finger]:
            self.message = f'{finger}: no servo answers on id {self.ids[finger]}.'
            return
        self.release()
        servo_id = self.ids[finger]
        position = from_u16(self.bus.read(servo_id, feetech.ADDR_PRESENT_POSITION, 2))
        self.bus.write(servo_id, feetech.ADDR_TORQUE_LIMIT, u16(self.torque))
        self.bus.write(servo_id, feetech.ADDR_GOAL_POSITION, u16(position))  # goal first, then torque
        self.bus.write(servo_id, feetech.ADDR_TORQUE_ENABLE, [1])
        self.active, self.goal = finger, position
        self.message = f'{finger}: move it with the arrows, then Set OPEN / Set CLOSED.'

    def nudge(self, delta):
        if self.active is not None and not self.testing:
            self._go(self.goal + delta)

    def set_open(self):
        self._set(self.open, 'OPEN')

    def set_closed(self):
        self._set(self.closed, 'CLOSED')

    def _set(self, store, name):
        finger = self.active
        if finger is None or self.testing:
            return
        store[finger] = self.goal
        self.message = f'{finger}: {name} = {self.goal}.' + self.warning(finger)

    def warning(self, finger):
        """Said, never asked: the person at the hand sees the mechanism, this only knows the CAD."""
        if finger not in self.open or finger not in self.closed:
            return ''
        span = abs(self.closed[finger] - self.open[finger])
        if span < 50:
            return '  OPEN and CLOSED are almost the same position.'
        limit = round(self.linkage[finger]['lock_rad'] * STEPS_PER_RAD) - LOCK_MARGIN_STEPS
        if span > limit:
            return (f'  WARNING: {span} steps = {span / STEPS_PER_RAD * 57.3:.0f} deg of horn. By the CAD this '
                    f'linkage binds at {self.linkage[finger]["lock_rad"] * 57.3:.0f} deg - stay under {limit} steps.')
        return ''

    def result(self):
        return {f: (self.open[f], self.closed[f]) for f in FINGERS if f in self.open and f in self.closed}

    # -- optional: watch the travel between the two positions, slowly -----------------------------

    def toggle_test(self):
        finger = self.active
        if self.testing:
            self.testing, self._test = False, None
            self.message = f'{finger}: stopped at {self.goal}.'
        elif finger in self.result():
            self._test = ([self.closed[finger], self.open[finger]], deque(maxlen=BLOCKED_TICKS))
            self.testing = True
            self.message = f'{finger}: to CLOSED and back to OPEN, slowly. Stop holds it where it is.'

    def tick(self, position):
        """Call every TICK_MS with the active finger's measured step."""
        if not self.testing or position is None:
            return
        waypoints, recent = self._test
        recent.append(position)
        stuck = len(recent) == recent.maxlen and abs(recent[-1] - recent[0]) < BLOCKED_MOTION_STEPS
        if stuck and abs(self.goal - position) > BLOCKED_ERROR_STEPS:
            self._go(position)  # stop pushing
            self.testing, self._test = False, None
            self.message = f'{self.active}: BLOCKED at {position} - stopped pushing.'
            return
        target = waypoints[0]
        if self.goal == target:
            if abs(position - target) <= 15:
                waypoints.pop(0)
                recent.clear()
                if not waypoints:
                    self.testing, self._test = False, None
                    self.message = f'{self.active}: travel done.'
            return
        self._go(self.goal + max(-TEST_STEPS_PER_TICK, min(TEST_STEPS_PER_TICK, target - self.goal)))

    def release(self):
        """Torque off for the active finger."""
        if self.active is None:
            return
        try:
            self.bus.write(self.ids[self.active], feetech.ADDR_TORQUE_ENABLE, [0])
        except FeetechError:
            pass
        self.active, self.goal, self.testing, self._test = None, None, False, None

    def lines(self):
        return {finger: f'  {finger + ":":7s} {{id: {self.ids[finger]}, open_step: {o}, closed_step: {c}}}'
                for finger, (o, c) in self.result().items()}

    def _go(self, step):
        self.goal = min(max(int(step), 0), 4095)
        self.bus.write(self.ids[self.active], feetech.ADDR_GOAL_POSITION, u16(self.goal))


class CalibrateWindow:
    """The window. Everything it shows comes from the Calibrator."""

    NUDGES = [(-100, '◀◀'), (-10, '◀'), (10, '▶'), (100, '▶▶')]

    def __init__(self, root, calibrator, save):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.cal, self.save = root, calibrator, save
        root.title('Hand calibration')
        frame = ttk.Frame(root, padding=14)
        frame.grid()
        ttk.Label(frame, text='Pick a finger  ·  move it (← → = 10 steps, Shift = 100)  ·  Set OPEN  ·  '
                              'move it  ·  Set CLOSED  ·  Save').grid(row=0, column=0, columnspan=3, sticky='w',
                                                                       pady=(0, 10))
        self.rows = {}
        for n, finger in enumerate(FINGERS):
            pick = tk.Button(frame, text=finger, width=9, command=lambda f=finger: self.do(self.cal.select, f))
            pick.grid(row=n + 1, column=0, padx=(0, 8), pady=2)
            position = ttk.Label(frame, width=10, anchor='e', font=('TkFixedFont', 11))
            position.grid(row=n + 1, column=1)
            status = ttk.Label(frame, width=52, anchor='w')
            status.grid(row=n + 1, column=2, padx=10, sticky='w')
            self.rows[finger] = (pick, position, status)

        controls = ttk.Frame(frame)
        controls.grid(row=len(FINGERS) + 1, column=0, columnspan=3, pady=(12, 4), sticky='w')
        self.needs_finger = [tk.Button(controls, text=label, width=4, command=lambda d=delta: self.do(self.cal.nudge, d))
                             for delta, label in self.NUDGES]
        self.needs_finger += [
            tk.Button(controls, text='Set OPEN', width=12, command=lambda: self.do(self.cal.set_open)),
            tk.Button(controls, text='Set CLOSED', width=12, command=lambda: self.do(self.cal.set_closed))]
        self.test = tk.Button(controls, text='Test', width=8, command=lambda: self.do(self.cal.toggle_test))
        for n, button in enumerate(self.needs_finger + [self.test]):
            button.grid(row=0, column=n, padx=(14 if n in (4, 6) else 2, 2))

        self.message = ttk.Label(frame, wraplength=700, justify='left', foreground='#8a3b00')
        self.message.grid(row=len(FINGERS) + 2, column=0, columnspan=3, sticky='w', pady=(8, 8))
        bottom = ttk.Frame(frame)
        bottom.grid(row=len(FINGERS) + 3, column=0, columnspan=3, sticky='w')
        self.save_button = tk.Button(bottom, text='Save', width=14, command=self.on_save)
        self.save_button.grid(row=0, column=0)
        tk.Button(bottom, text='Release (torque off)', width=20,
                  command=lambda: self.do(self.cal.release)).grid(row=0, column=1, padx=8)

        for keys, delta in (('<Left>', -10), ('<Right>', 10), ('<Shift-Left>', -100), ('<Shift-Right>', 100)):
            root.bind(keys, lambda _, d=delta: self.do(self.cal.nudge, d))
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()
        root.after(TICK_MS, self.tick)

    def do(self, action, *args):
        try:
            action(*args)
        except FeetechError as error:
            self.cal.message = f'The servo did not answer ({error}). Power and cable?'
        self.refresh()

    def on_save(self):
        self.do(self.cal.release)
        self.cal.message = self.save(self.cal.lines())
        self.refresh()

    def tick(self):
        try:
            positions = self.cal.positions()
        except FeetechError:
            positions = {finger: None for finger in FINGERS}
        for finger, (_, label, _) in self.rows.items():
            step = positions[finger]
            label.config(text='no servo' if not self.cal.present[finger] else '----' if step is None else f'{step:4d}')
        if self.cal.testing:
            self.do(self.cal.tick, positions[self.cal.active])
        self.root.after(TICK_MS, self.tick)

    def refresh(self):
        cal = self.cal
        for finger, (pick, _, status) in self.rows.items():
            pick.config(relief='sunken' if finger == cal.active else 'raised',
                        state='normal' if cal.present[finger] else 'disabled')
            o, c = cal.open.get(finger), cal.closed.get(finger)
            file_open, file_closed = cal.saved(finger)
            done = '✓ ' if o is not None and c is not None else ''
            status.config(text=f'{done}open {"—" if o is None else o}    closed {"—" if c is None else c}'
                               f'        (file: {file_open} → {file_closed})')
        for button in self.needs_finger:
            button.config(state='normal' if cal.active and not cal.testing else 'disabled')
        self.test.config(text='Stop' if cal.testing else 'Test',
                         state='normal' if cal.testing or (cal.active in cal.result()) else 'disabled')
        self.save_button.config(state='normal' if cal.result() else 'disabled')
        self.message.config(text=cal.message)

    def close(self):
        self.do(self.cal.release)
        self.root.destroy()
