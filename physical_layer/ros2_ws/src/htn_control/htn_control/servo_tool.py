"""Set up Feetech bus servos: find them, give them ids, find calibration steps.

    servo_tool scan
    servo_tool set-id 1 3        (one servo on the bus at a time)
    servo_tool jog 3             (j/k = 10 steps, J/K = 100 steps, q = quit)
    servo_tool calibrate         (a window: set each finger's open pose -> hand_params.yaml)
"""
import argparse
import math
import re
import sys
import termios
import tty

from htn_control.hal import feetech
from htn_control.hal.feetech import FeetechBus, FeetechError, from_u16, u16
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
        else:
            jog(bus, args.id, args.torque)
    finally:
        bus.close()


if __name__ == '__main__':
    main()
