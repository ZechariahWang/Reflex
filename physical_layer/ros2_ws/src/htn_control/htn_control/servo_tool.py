"""Set up Feetech bus servos: find them, give them ids, find calibration steps.

    servo_tool scan
    servo_tool set-id 1 3        (one servo on the bus at a time)
    servo_tool jog 3             (j/k = 10 steps, J/K = 100 steps, q = quit)
    servo_tool calibrate         (every finger: open pose + closing direction -> hand_params.yaml)
    servo_tool calibrate --fingers index ring --write
"""
import argparse
import math
import re
import sys
import termios
import tty

from htn_control.hal import feetech
from htn_control.hal.feetech import FeetechBus, FeetechError, from_u16, u16
from htn_control.hand_config import FINGERS, default_params_file, load_hand_params, load_linkage

JOG_KEYS = {'j': -10, 'k': 10, 'J': -100, 'K': 100}
STEPS_PER_RAD = 4096 / (2 * math.pi)
DIRECTION_TEST_STEPS = 80  # ~7 deg of horn: enough to see which way the finger goes


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


def jog(bus, servo_id, torque, accept=None):
    """Move one servo with the keys. With `accept` (a key), that key ends it and the goal is
    returned with the torque still ON (calibrate goes on from there); q always gives up."""
    position = from_u16(bus.read(servo_id, feetech.ADDR_PRESENT_POSITION, 2))
    bus.write(servo_id, feetech.ADDR_TORQUE_LIMIT, u16(torque))
    bus.write(servo_id, feetech.ADDR_GOAL_POSITION, u16(position))
    bus.write(servo_id, feetech.ADDR_TORQUE_ENABLE, [1])
    old_settings = termios.tcgetattr(sys.stdin)
    accepted = False
    try:
        tty.setcbreak(sys.stdin.fileno())
        while True:
            hint = 'j/k 10, J/K 100, ' + ('Enter = this is the pose, q = skip' if accept else 'q quit')
            print(f'\rgoal {position:4d}  ({hint}) ', end='', flush=True)
            key = sys.stdin.read(1)
            if key == 'q':
                break
            if accept and key in accept:
                accepted = True
                break
            position = min(max(position + JOG_KEYS.get(key, 0), 0), 4095)
            bus.write(servo_id, feetech.ADDR_GOAL_POSITION, u16(position))
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        if not accepted:
            bus.write(servo_id, feetech.ADDR_TORQUE_ENABLE, [0])
        print()
    return position if accepted else None


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
                f'put it back so that the open pose reads about 2048, and calibrate this finger again.')
    return None


def yaml_line(finger, servo_id, open_step, closed):
    return f'  {finger + ":":7s} {{id: {servo_id}, open_step: {open_step}, closed_step: {closed}}}'


def rewrite_yaml(text, lines):
    """Replace the `  <finger>: {id: ...}` lines of the servos section; everything else stays."""
    for finger, line in lines.items():
        text, count = re.subn(rf'^  {finger}:\s*\{{id:[^}}]*\}}[^\n]*$', line, text, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f'no single "  {finger}: {{id: ...}}" line in the parameter file')
    return text


def calibrate(bus, fingers, torque, params_file, write):
    params, linkage = load_hand_params(params_file), load_linkage()
    print('One finger at a time, at a low torque. Keep hands out of the exoskeleton.\n'
          'OPEN is the pose of the CAD: the 3D view of the web console at 0 %, fingers straight.\n'
          'The servos cannot be pushed by hand, and "drive until it stops" is no way to find open:\n'
          'opening, the linkage binds ~30 deg of horn past that pose, on its own pins.\n')
    lines = {}
    for finger in fingers:
        servo_id = params['servos'][finger]['id']
        if not bus.ping(servo_id):
            print(f'{finger}: no servo with id {servo_id}, skipped')
            continue
        print(f'{finger} (id {servo_id}): jog it to the OPEN pose.')
        open_step = jog(bus, servo_id, torque, accept='\r\n')
        if open_step is None:
            print(f'{finger}: skipped')
            continue
        try:
            bus.write(servo_id, feetech.ADDR_GOAL_POSITION, u16(min(open_step + DIRECTION_TEST_STEPS, 4095)))
            answer = input(f'{finger}: it moved a little. Towards CLOSED (curling in)? [y/n] ').strip().lower()
            bus.write(servo_id, feetech.ADDR_GOAL_POSITION, u16(open_step))
        finally:
            input('back at open - Enter to release this finger ')
            bus.write(servo_id, feetech.ADDR_TORQUE_ENABLE, [0])
        closed = closed_step(open_step, answer.startswith('y'), params['fingers'][finger]['max_angle'])
        problem = check_travel(finger, open_step, closed, linkage[finger]['open_lock_rad'])
        if problem:
            print(problem)
            continue
        lines[finger] = yaml_line(finger, servo_id, open_step, closed)
        print(lines[finger].strip(), '\n')
    if not lines:
        return
    print('servos: section of hand_params.yaml:')
    print('\n'.join(lines.values()))
    if write:
        path = params_file or default_params_file()
        with open(path) as f:
            text = f.read()
        with open(path, 'w') as f:
            f.write(rewrite_yaml(text, lines))
        print(f'written to {path} - restart the launch (no rebuild needed)')


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
    calibrate_parser.add_argument('--fingers', nargs='+', choices=FINGERS, default=FINGERS)
    calibrate_parser.add_argument('--torque', type=int, default=150, help='torque limit, 0..1000')
    calibrate_parser.add_argument('--params-file', default='')
    calibrate_parser.add_argument('--write', action='store_true', help='put the values into hand_params.yaml')
    args = parser.parse_args()

    bus = FeetechBus(args.port, args.baud)
    try:
        if args.command == 'scan':
            scan(bus)
        elif args.command == 'set-id':
            set_id(bus, args.old, args.new)
            print(f'id {args.old} -> {args.new}')
        elif args.command == 'calibrate':
            calibrate(bus, args.fingers, args.torque, args.params_file, args.write)
        else:
            jog(bus, args.id, args.torque)
    finally:
        bus.close()


if __name__ == '__main__':
    main()
