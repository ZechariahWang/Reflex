"""Set up Feetech bus servos: find them, give them ids, find calibration steps.

    servo_tool scan
    servo_tool set-id 1 3        (one servo on the bus at a time)
    servo_tool jog 3             (j/k = 10 steps, J/K = 100 steps, q = quit)
    servo_tool calibrate         (a window: set each finger's open pose -> hand_params.yaml)
    servo_tool probe 3           (close and open one finger, log position / load / current)
"""
import argparse
import math
import re
import sys
import statistics
import termios
import time
import tty

from htn_control.hal import feetech
from htn_control.hal.feetech import FeetechBus, FeetechError, from_sign_magnitude, from_u16, u16
from htn_control.hand_config import default_params_file, load_hand_params, load_linkage

JOG_KEYS = {'j': -10, 'k': 10, 'J': -100, 'K': 100}


def scan(bus, ids=range(254)):
    for servo_id in ids:
        if not bus.ping(servo_id):
            continue
        try:
            position = from_u16(bus.read(servo_id, feetech.ADDR_PRESENT_POSITION, 2))
            print(f'id {servo_id}: position {position}')
        except FeetechError as error:
            # Identical ping replies overlap cleanly, position replies collide
            print(f'id {servo_id}: answers a ping, not a read ({error}) - several servos on this id?')


def set_id(bus, old, new):
    if not 0 <= new <= 253:
        raise ValueError(f'id must be 0..253, got {new}')
    if bus.ping(new):
        raise ValueError(f'id {new} is already on the bus')
    bus.write(old, feetech.ADDR_LOCK, [0])
    try:
        bus.write(old, feetech.ADDR_ID, [new])
    except FeetechError:
        pass  # the reply can come from the old or the new id
    bus.write(new, feetech.ADDR_LOCK, [1])


def jog(bus, servo_id, torque):
    position = from_u16(bus.read(servo_id, feetech.ADDR_PRESENT_POSITION, 2))
    bus.write(servo_id, feetech.ADDR_TORQUE_LIMIT, u16(torque))
    bus.write(servo_id, feetech.ADDR_GOAL_POSITION, u16(position))
    bus.write(servo_id, feetech.ADDR_TORQUE_ENABLE, [1])
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while True:
            print(f'\rgoal {position:4d}  (j/k 10, J/K 100, q quit) ', end='', flush=True)
            key = sys.stdin.read(1)
            if key == 'q':
                break
            position = min(max(position + JOG_KEYS.get(key, 0), 0), 4095)
            bus.write(servo_id, feetech.ADDR_GOAL_POSITION, u16(position))
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        bus.write(servo_id, feetech.ADDR_TORQUE_ENABLE, [0])
        print()


def probe(bus, servo_id, torque, speed, params_file, rate=50.0, stop_current=None, stop_cycles=5):
    """Close, hold, open one finger the way the HAL does (a swept goal, `speed` in finger travel
    per second) and log what the servo reports, to choose the contact stop's current threshold:
    run it once with the finger free and once blocked by hand. The HAL must not be running.
    With `stop_current` (mA) it tries that threshold the way the contact stop uses it: above
    it for `stop_cycles` samples in a row, the finger stops where it is for the rest of the phase."""
    servos = load_hand_params(params_file)['servos']
    finger, servo = next((name, s) for name, s in servos.items() if isinstance(s, dict) and s['id'] == servo_id)
    open_step, closed_step = servo['open_step'], servo['closed_step']
    step = speed * abs(closed_step - open_step) / rate
    phases = [('close', closed_step, 3.0), ('hold', None, 1.0), ('open', open_step, 3.0)]  # hold: where close ended
    currents = {name: [] for name, _, _ in phases}
    goal = from_u16(bus.read(servo_id, feetech.ADDR_PRESENT_POSITION, 2))
    bus.write(servo_id, feetech.ADDR_TORQUE_LIMIT, u16(torque))
    bus.write(servo_id, feetech.ADDR_GOAL_POSITION, u16(goal))
    bus.write(servo_id, feetech.ADDR_TORQUE_ENABLE, [1])
    print('t,phase,goal,position,load,current_mA')
    start = time.monotonic()
    try:
        for phase, target, seconds in phases:
            over, target = 0, goal if target is None else target
            for _ in range(int(seconds * rate)):
                goal += min(max(target - goal, -step), step)
                bus.write(servo_id, feetech.ADDR_GOAL_POSITION, u16(round(goal)))
                # position .. current is one block, like the vendor SDK reads it
                data = bus.read(servo_id, feetech.ADDR_PRESENT_POSITION, 15)
                load = from_sign_magnitude(data[4:6], 10)
                current = from_sign_magnitude(data[13:15], 15) * feetech.CURRENT_MA
                currents[phase].append(abs(current))
                over = over + 1 if stop_current is not None and abs(current) >= stop_current else 0
                if over == stop_cycles and target != goal:
                    target = goal = from_u16(data[:2])
                    print(f'# {finger} {phase}: stopped at step {goal}, {abs(current):.0f} mA', file=sys.stderr)
                print(f'{time.monotonic() - start:.2f},{phase},{round(goal)},{from_u16(data[:2])},{load},{current:.0f}')
                time.sleep(1.0 / rate)
    finally:
        bus.write(servo_id, feetech.ADDR_TORQUE_ENABLE, [0])
    for phase, values in currents.items():
        print(f'# {finger} {phase:5s}: median {statistics.median(values):4.0f} mA, peak {max(values):4.0f} mA',
              file=sys.stderr)


def yaml_line(finger, servo_id, open_step, closed):
    return f'  {finger + ":":7s} {{id: {servo_id}, open_step: {open_step}, closed_step: {closed}}}'


def rewrite_yaml(text, lines):
    """Replace the `  <finger>: {id: ...}` lines of the servos section (a rewritten line has no
    `enabled: false` any more: a calibrated finger is driven) and set each finger's max_angle
    to the travel that was set, so the URDF, the HAL's joint states and the 3D views agree with
    the servo. Everything else in the file stays."""
    for finger, line in lines.items():
        text, count = re.subn(rf'^  {finger}:\s*\{{id:[^}}]*\}}[^\n]*$', line, text, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f'no single "  {finger}: {{id: ...}}" line in the parameter file')
        open_step, closed = (int(v) for v in re.search(r'open_step: (\d+), closed_step: (\d+)', line).groups())
        travel = abs(closed - open_step) * 2 * math.pi / 4096
        text, count = re.subn(rf'^(  {finger}:\s*\{{min_angle: [^,]*, max_angle: )[^,]*(,[^\n]*\}})[^\n]*$',
                              rf'\g<1>{travel:.4f}\g<2>', text, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f'no single "  {finger}: {{min_angle: ..., max_angle: ...}}" line in the parameter file')
    return text


def calibrate(bus, torque, params_file):
    """The calibration window (calibrate_gui.py)."""
    import tkinter as tk

    from htn_control.calibrate_gui import CalibrateWindow, Calibrator
    path = params_file or default_params_file()
    calibrator = Calibrator(bus, load_hand_params(path), load_linkage(), torque)

    def save(lines):
        with open(path) as f:
            text = f.read()
        with open(path, 'w') as f:
            f.write(rewrite_yaml(text, lines))
        return f'Saved {", ".join(lines)} to {path}. Restart the launch - no rebuild needed.'

    root = tk.Tk()
    CalibrateWindow(root, calibrator, save)
    try:
        root.mainloop()
    finally:
        calibrator.release()  # never leave a finger powered when the window goes away


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', default='/dev/ttyACM0')
    parser.add_argument('--baud', type=int, default=1_000_000)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('scan')
    set_id_parser = commands.add_parser('set-id')
    set_id_parser.add_argument('old', type=int)
    set_id_parser.add_argument('new', type=int)
    jog_parser = commands.add_parser('jog')
    jog_parser.add_argument('id', type=int)
    jog_parser.add_argument('--torque', type=int, default=200, help='torque limit, 0..1000')
    calibrate_parser = commands.add_parser('calibrate')
    calibrate_parser.add_argument('--torque', type=int, default=150, help='torque limit, 0..1000')
    calibrate_parser.add_argument('--params-file', default='')
    probe_parser = commands.add_parser('probe')
    probe_parser.add_argument('id', type=int)
    probe_parser.add_argument('--torque', type=int, default=300, help='torque limit, 0..1000')
    probe_parser.add_argument('--speed', type=float, default=2.0, help='finger travel per second, as the HAL max_speed')
    probe_parser.add_argument('--stop-current', type=float, help='mA: stop the finger above this, like the contact stop')
    probe_parser.add_argument('--params-file', default='')
    args = parser.parse_args()

    bus = FeetechBus(args.port, args.baud)
    try:
        if args.command == 'scan':
            scan(bus)
        elif args.command == 'set-id':
            set_id(bus, args.old, args.new)
            print(f'id {args.old} -> {args.new}')
        elif args.command == 'calibrate':
            calibrate(bus, args.torque, args.params_file)
        elif args.command == 'probe':
            probe(bus, args.id, args.torque, args.speed, args.params_file, stop_current=args.stop_current)
        else:
            jog(bus, args.id, args.torque)
    finally:
        bus.close()


if __name__ == '__main__':
    main()
