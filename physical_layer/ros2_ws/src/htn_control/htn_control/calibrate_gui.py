"""Calibration window for the real hand: where is OPEN, and which way does each servo close.

    ros2 run htn_control servo_tool calibrate

Per finger: pick it, nudge it straight, say "this is open", say which way it
twitched, watch a slow test of the whole travel. Save writes hand_params.yaml.
`Calibrator` is the logic (no tkinter, tested on the fake servo bus);
`CalibrateWindow` only draws it.
"""
import math
from collections import deque

from htn_control.hal import feetech
from htn_control.hal.feetech import FeetechError, from_u16, u16
from htn_control.hand_config import FINGERS

STEPS_PER_RAD = 4096 / (2 * math.pi)
TWITCH_STEPS = 80        # ~7 deg of horn: enough to see which way the finger goes
TEST_STEPS_PER_TICK = 6  # at TICK_MS: ~13 deg of horn per second
TICK_MS = 40
BLOCKED_ERROR_STEPS = 90   # the goal is this far ahead ...
BLOCKED_TICKS = 12         # ... and the servo moved less than BLOCKED_MOTION_STEPS in this many ticks
BLOCKED_MOTION_STEPS = 4


def closed_step(open_step, closes_with_more_steps, max_angle):
    """<finger>_joint is the servo horn: closed is max_angle of horn from open, either way round."""
    span = round(max_angle * STEPS_PER_RAD)
    return open_step + span if closes_with_more_steps else open_step - span


def check_travel(finger, open_step, closed, open_lock_rad):
    """The encoder wraps at 0 / 4095. The whole travel, and the way back out of a finger that
    was opened too far, must stay clear of it."""
    beyond_open = round(open_lock_rad * STEPS_PER_RAD)
    towards_open = open_step - beyond_open if closed > open_step else open_step + beyond_open
    low, high = min(closed, towards_open), max(closed, towards_open)
    if low < 50 or high > 4045:
        return (f'{finger}: travel {low} .. {high} runs into the encoder wrap (0 / 4095). Take the horn off, '
                f'put it back so that the open pose reads about 2048, and do this finger again.')
    return None


class Calibrator:
    """One finger is active at a time and only that one has torque.

    Steps of a finger: 'idle' -> select() -> 'nudge' -> set_open() -> 'which_way'
    -> answer() -> 'done' (-> start_test() -> 'testing' -> 'done').
    """

    def __init__(self, bus, params, linkage, torque=150):
        self.bus, self.params, self.linkage, self.torque = bus, params, linkage, torque
        self.ids = {finger: params['servos'][finger]['id'] for finger in FINGERS}
        self.present = {finger: bus.ping(self.ids[finger]) for finger in FINGERS}
        self.step = {finger: 'idle' for finger in FINGERS}
        self.result = {}        # finger -> (open_step, closed_step), set in this session
        self.active = None
        self.goal = None
        self.message = 'Pick a finger to start.'
        self._test = None       # (waypoints left, recent positions)

    # -- reading ---------------------------------------------------------------------------

    def positions(self):
        ids = [self.ids[f] for f in FINGERS if self.present[f]]
        replies = self.bus.sync_read(feetech.ADDR_PRESENT_POSITION, 2, ids) if ids else {}
        return {f: from_u16(replies[self.ids[f]]) if self.ids[f] in replies else None for f in FINGERS}

    def saved(self, finger):
        servo = self.params['servos'][finger]
        return servo['open_step'], servo['closed_step']

    # -- the steps of one finger --------------------------------------------------------------

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
        self.step[finger] = 'nudge'
        self.message = (f'{finger}: nudge it until the finger is STRAIGHT (the open pose, like the 3D view '
                        f'at 0 %), then press "This is open".')

    def nudge(self, delta):
        if self.active is None or self.step[self.active] not in ('nudge', 'done'):
            return
        self._go(self.goal + delta)
        if self.step[self.active] == 'done':   # moved after it was finished: open has to be set again
            self.step[self.active] = 'nudge'
            self.result.pop(self.active, None)
            self.message = f'{self.active}: moved - press "This is open" again when it is straight.'

    def set_open(self):
        finger = self.active
        if finger is None or self.step[finger] != 'nudge':
            return
        self._open = self.goal
        self._go(self._open + TWITCH_STEPS)
        self.step[finger] = 'which_way'
        self.message = f'{finger} just moved a little. Which way did it go?'

    def answer(self, curled_in):
        finger = self.active
        if finger is None or self.step[finger] != 'which_way':
            return
        self._go(self._open)
        closed = closed_step(self._open, curled_in, self.params['fingers'][finger]['max_angle'])
        problem = check_travel(finger, self._open, closed, self.linkage[finger]['open_lock_rad'])
        if problem:
            self.step[finger] = 'nudge'
            self.message = problem
            return
        self.result[finger] = (self._open, closed)
        self.step[finger] = 'done'
        self.message = (f'{finger}: open {self._open}, closed {closed}. "Test the travel" shows the whole '
                        f'range slowly - or pick the next finger.')

    # -- slow test of the whole travel ---------------------------------------------------------------

    def start_test(self):
        finger = self.active
        if finger is None or self.step[finger] != 'done':
            return
        open_step, closed = self.result[finger]
        self._test = ([closed, open_step], deque(maxlen=BLOCKED_TICKS))
        self.step[finger] = 'testing'
        self.message = f'{finger}: closing slowly, then opening again. Watch it - "Stop" holds it where it is.'

    def stop_test(self):
        if self.active is not None and self.step[self.active] == 'testing':
            self._test = None
            self.step[self.active] = 'done'
            self.message = f'{self.active}: stopped at {self.goal}. Nudge it, or test again.'

    def tick(self, position):
        """Call every TICK_MS with the active finger's measured step while testing."""
        if self._test is None or position is None:
            return
        waypoints, recent = self._test
        recent.append(position)
        stuck = len(recent) == recent.maxlen and abs(recent[-1] - recent[0]) < BLOCKED_MOTION_STEPS
        if stuck and abs(self.goal - position) > BLOCKED_ERROR_STEPS:
            self._go(position)  # stop pushing
            self._test = None
            self.step[self.active] = 'done'
            self.message = (f'{self.active}: BLOCKED at {position} - it stopped pushing. Something is in the '
                            f'way, or "open" is off. Nudge it free and set open again.')
            return
        target = waypoints[0]
        if self.goal == target:
            if abs(position - target) <= 15:     # arrived: on to the next waypoint
                waypoints.pop(0)
                recent.clear()
                if not waypoints:
                    self._test = None
                    self.step[self.active] = 'done'
                    self.message = f'{self.active}: travel is fine. Pick the next finger, or Save.'
            return
        move = max(-TEST_STEPS_PER_TICK, min(TEST_STEPS_PER_TICK, target - self.goal))
        self._go(self.goal + move)

    # -- finishing -------------------------------------------------------------------------------

    def release(self):
        """Torque off for the active finger."""
        if self.active is None:
            return
        try:
            self.bus.write(self.ids[self.active], feetech.ADDR_TORQUE_ENABLE, [0])
        except FeetechError:
            pass
        if self.step[self.active] in ('nudge', 'which_way', 'testing'):
            self.step[self.active] = 'done' if self.active in self.result else 'idle'
        self.active, self.goal, self._test = None, None, None

    def lines(self):
        return {finger: f'  {finger + ":":7s} {{id: {self.ids[finger]}, open_step: {o}, closed_step: {c}}}'
                for finger, (o, c) in self.result.items()}

    def _go(self, step):
        self.goal = min(max(int(step), 0), 4095)
        self.bus.write(self.ids[self.active], feetech.ADDR_GOAL_POSITION, u16(self.goal))


class CalibrateWindow:
    """The window. Everything it shows comes from the Calibrator."""

    NUDGES = [(-100, '◀◀'), (-10, '◀'), (10, '▶'), (100, '▶▶')]
    STEP_TEXT = {'idle': 'not done', 'nudge': 'set open…', 'which_way': 'which way?', 'testing': 'testing…'}

    def __init__(self, root, calibrator, save):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.root, self.cal, self.save = tk, root, calibrator, save
        root.title('Hand calibration')
        frame = ttk.Frame(root, padding=14)
        frame.grid()
        ttk.Label(frame, justify='left', text=(
            '1. Pick a finger - only that one gets (a little) torque.\n'
            '2. Nudge it until the finger is STRAIGHT, then "This is open".   (← → = 10 steps, Shift = 100)\n'
            '3. It twitches: say which way it went.  4. "Test the travel" to watch the whole range.  5. Save.'
        )).grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 10))

        self.rows = {}
        for n, finger in enumerate(FINGERS):
            pick = tk.Button(frame, text=finger, width=9, command=lambda f=finger: self.do(self.cal.select, f))
            pick.grid(row=n + 1, column=0, padx=(0, 8), pady=2)
            position = ttk.Label(frame, width=12, anchor='e', font=('TkFixedFont', 11))
            position.grid(row=n + 1, column=1)
            status = ttk.Label(frame, width=44, anchor='w')
            status.grid(row=n + 1, column=2, padx=10, sticky='w')
            self.rows[finger] = (pick, position, status)

        controls = ttk.Frame(frame)
        controls.grid(row=len(FINGERS) + 1, column=0, columnspan=4, pady=(12, 4), sticky='w')
        self.nudges = [tk.Button(controls, text=label, width=4, command=lambda d=delta: self.do(self.cal.nudge, d))
                       for delta, label in self.NUDGES]
        for n, button in enumerate(self.nudges):
            button.grid(row=0, column=n, padx=2)
        self.open_button = tk.Button(controls, text='This is open', width=14, command=lambda: self.do(self.cal.set_open))
        self.open_button.grid(row=0, column=4, padx=(14, 2))
        self.curled = tk.Button(controls, text='It curled IN', width=12, command=lambda: self.do(self.cal.answer, True))
        self.opened = tk.Button(controls, text='It opened OUT', width=12, command=lambda: self.do(self.cal.answer, False))
        self.curled.grid(row=0, column=5, padx=2)
        self.opened.grid(row=0, column=6, padx=2)
        self.test = tk.Button(controls, text='Test the travel', width=14, command=self.toggle_test)
        self.test.grid(row=0, column=7, padx=(14, 2))

        self.message = ttk.Label(frame, wraplength=760, justify='left', foreground='#8a3b00')
        self.message.grid(row=len(FINGERS) + 2, column=0, columnspan=4, sticky='w', pady=(8, 8))
        bottom = ttk.Frame(frame)
        bottom.grid(row=len(FINGERS) + 3, column=0, columnspan=4, sticky='w')
        self.save_button = tk.Button(bottom, text='Save to hand_params.yaml', width=26, command=self.on_save)
        self.save_button.grid(row=0, column=0)
        tk.Button(bottom, text='Release (torque off)', width=20,
                  command=lambda: self.do(self.cal.release)).grid(row=0, column=1, padx=8)

        root.bind('<Left>', lambda _: self.do(self.cal.nudge, -10))
        root.bind('<Right>', lambda _: self.do(self.cal.nudge, 10))
        root.bind('<Shift-Left>', lambda _: self.do(self.cal.nudge, -100))
        root.bind('<Shift-Right>', lambda _: self.do(self.cal.nudge, 100))
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()
        root.after(TICK_MS, self.tick)

    def do(self, action, *args):
        try:
            action(*args)
        except FeetechError as error:
            self.cal.message = f'The servo did not answer ({error}). Power and cable?'
        self.refresh()

    def toggle_test(self):
        testing = self.cal.active and self.cal.step[self.cal.active] == 'testing'
        self.do(self.cal.stop_test if testing else self.cal.start_test)

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
        if self.cal.active:
            before = self.cal.step[self.cal.active]
            self.do(self.cal.tick, positions[self.cal.active])
            if before != self.cal.step.get(self.cal.active, before):
                self.refresh()
        self.root.after(TICK_MS, self.tick)

    def refresh(self):
        cal = self.cal
        step = cal.step[cal.active] if cal.active else None
        for finger, (pick, _, status) in self.rows.items():
            pick.config(relief='sunken' if finger == cal.active else 'raised',
                        state='normal' if cal.present[finger] else 'disabled')
            if finger in cal.result and cal.step[finger] in ('done', 'testing'):
                o, c = cal.result[finger]
                text = f'✓ open {o}  →  closed {c}' + ('   (testing…)' if cal.step[finger] == 'testing' else '')
            else:
                o, c = cal.saved(finger)
                text = f'{self.STEP_TEXT.get(cal.step[finger], "")}   (file has {o} → {c})'
            status.config(text=text)

        def enable(widget, on):
            widget.config(state='normal' if on else 'disabled')
        for button in self.nudges:
            enable(button, step in ('nudge', 'done'))
        enable(self.open_button, step == 'nudge')
        enable(self.curled, step == 'which_way')
        enable(self.opened, step == 'which_way')
        enable(self.test, step in ('done', 'testing'))
        self.test.config(text='Stop' if step == 'testing' else 'Test the travel')
        enable(self.save_button, bool(cal.result))
        self.message.config(text=cal.message)

    def close(self):
        self.do(self.cal.release)
        self.root.destroy()
