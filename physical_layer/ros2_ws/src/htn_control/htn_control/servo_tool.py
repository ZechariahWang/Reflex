"""Set up Feetech bus servos: find them, give them ids, find calibration steps.

    servo_tool scan
    servo_tool set-id 1 3        (one servo on the bus at a time)
    servo_tool jog 3             (j/k = 10 steps, J/K = 100 steps, q = quit)
"""
import argparse
import sys
import termios
import tty

from htn_control.hal import feetech
from htn_control.hal.feetech import FeetechBus, FeetechError, from_u16, u16

JOG_KEYS = {'j': -10, 'k': 10, 'J': -100, 'K': 100}


def scan(bus):
    for servo_id in range(254):
        if bus.ping(servo_id):
            position = from_u16(bus.read(servo_id, feetech.ADDR_PRESENT_POSITION, 2))
            print(f'id {servo_id}: position {position}')


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
    args = parser.parse_args()

    bus = FeetechBus(args.port, args.baud)
    try:
        if args.command == 'scan':
            scan(bus)
        elif args.command == 'set-id':
            set_id(bus, args.old, args.new)
            print(f'id {args.old} -> {args.new}')
        else:
            jog(bus, args.id, args.torque)
    finally:
        bus.close()


if __name__ == '__main__':
    main()
