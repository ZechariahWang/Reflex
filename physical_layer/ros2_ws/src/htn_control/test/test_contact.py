"""Contact stop: the detector on its own, then the HAL on fake servos that move and can be blocked."""
import os

import pytest

from htn_control.hal import feetech
from htn_control.hal.contact import BLOCKED, FREE, ContactDetector
from htn_control.hal.feetech import from_u16, u16
from test_feetech import FakeServos

IDS = [1, 2, 3, 4, 5]
OPEN, CLOSED = 2048, 3072  # hand_params.yaml before calibration; any pair works here


def detector():
    return ContactDetector(hold_lead=0.03, release_travel=0.15, blocked_current=100, blocked_excess=150)


def block(contact, at, direction=1.0, target=None):
    target = at + 0.5 * direction if target is None else target
    assert contact.update(at + 0.1 * direction, at, target, current=300) == BLOCKED
    return target


def test_far_from_the_setpoint_and_not_moving_at_a_low_current_is_free():
    contact = detector()
    assert all(contact.update(0.6, 0.30, 1.0, current=60) == FREE for _ in range(100))


def test_some_cycles_a_little_over_the_threshold_block():
    contact = detector()
    states = [contact.update(0.53 + 0.003 * n, 0.50 + 0.003 * n, 0.6, current=150) for n in range(3)]
    assert states == [FREE, FREE, BLOCKED] and contact.direction == 1.0


def test_one_huge_cycle_blocks_at_once():
    contact = detector()
    assert contact.update(0.52, 0.50, 0.6, current=90) == FREE
    assert contact.update(0.52, 0.50, 0.6, current=260) == BLOCKED


def test_the_peak_of_a_free_start_drains_away_and_no_current_reading_does_not_block():
    contact = detector()
    # the middle finger on the hand, a free start, again and again: 34 mA over, then well below
    for current in [91, 110, 104, 110, 110, 78, 65] * 10 + [None] * 10:
        assert contact.update(0.52, 0.50, 0.6, current=current) == FREE


@pytest.mark.parametrize('direction', [1.0, -1.0])
def test_the_hold_setpoint_follows_the_finger_forward_and_never_goes_back(direction):
    contact = detector()
    target = block(contact, 0.5, direction)
    assert contact.hold_setpoint() == pytest.approx(0.5 + 0.03 * direction)
    contact.update(contact.hold_setpoint(), 0.5 + 0.08 * direction, target)  # it coasts on
    assert contact.hold_setpoint() == pytest.approx(0.5 + 0.11 * direction)
    contact.update(contact.hold_setpoint(), 0.5 + 0.06 * direction, target)  # the object pushes it back
    assert contact.state == BLOCKED and contact.hold_setpoint() == pytest.approx(0.5 + 0.11 * direction)


@pytest.mark.parametrize('direction', [1.0, -1.0])
def test_released_by_a_command_the_other_way_or_by_travel_past_release_travel(direction):
    contact = detector()
    target = block(contact, 0.5, direction)
    assert contact.update(contact.hold_setpoint(), 0.5, target) == BLOCKED  # still pushing: stays
    assert contact.update(contact.hold_setpoint(), 0.5, 0.5 - 0.3 * direction) == FREE

    block(contact, 0.5, direction)
    assert contact.update(contact.hold_setpoint(), 0.5 + 0.14 * direction, target) == BLOCKED  # a coast
    assert contact.update(contact.hold_setpoint(), 0.5 + 0.16 * direction, target) == FREE     # it goes on and on


# The index finger on the hand: a close at probe speed 2.0, a person resisting the whole move.
# (goal step, position step, mA) per 20 ms cycle; open 2028, closed 1213.
RESISTED_CLOSE = [
    (1998, 2031, 0), (1966, 2031, 0), (1933, 2031, 20), (1901, 2030, 26), (1868, 2026, 32), (1835, 2019, 58),
    (1803, 2009, 58), (1770, 1998, 65), (1738, 1984, 91), (1705, 1967, 110), (1672, 1949, 130),
    (1640, 1929, 169), (1607, 1906, 221), (1575, 1881, 247), (1542, 1855, 286), (1509, 1825, 254),
    (1477, 1793, 260), (1444, 1761, 266), (1412, 1728, 292), (1379, 1697, 234), (1346, 1663, 247),
]


def test_a_resisted_finger_at_speed_stays_blocked_while_it_coasts():
    """Found on the hand: 0.04 of the travel per cycle, so its own momentum met the old release
    (0.015 past the block) in the next cycle - low torque for 20 ms, then the full torque again."""
    contact, blocked_at = detector(), None
    for goal, step, current in RESISTED_CLOSE:
        setpoint, measured = (2028 - goal) / 815, (2028 - step) / 815
        state = contact.update(setpoint, measured, 1.0, current=current)
        if blocked_at is None and state == BLOCKED:
            blocked_at = measured
        if blocked_at is not None and measured - blocked_at <= 0.15:
            assert state == BLOCKED, f'let go at {measured:.3f}, blocked at {blocked_at:.3f}'
            assert contact.hold_setpoint() > measured, 'the servo must keep pushing, not pull back'
    assert blocked_at == pytest.approx(0.15, abs=0.01)


class MovingServos(FakeServos):
    """Fake servos that go to their goal while they have torque, up to a mechanical stop."""

    def __init__(self, ids, speed=25):
        self.stops = {}      # id -> (lowest, highest) reachable step
        self.speed = speed   # steps per position read
        self.limits = {}     # id -> torque limits written, in order
        super().__init__(ids)

    def store(self, servo_id, addr, data):
        if addr == feetech.ADDR_TORQUE_LIMIT:
            self.limits.setdefault(servo_id, []).append(from_u16(bytes(data)))
        super().store(servo_id, addr, data)

    def handle(self, servo_id, instruction, params):
        if instruction == feetech.SYNC_READ and params[0] == feetech.ADDR_PRESENT_POSITION:
            for i in params[2:]:
                registers = self.registers.get(i)
                if registers is None or registers[feetech.ADDR_TORQUE_ENABLE] == 0:
                    continue
                present, goal = from_u16(registers[56:58]), from_u16(registers[42:44])
                step = max(-self.speed, min(self.speed, goal - present))
                low, high = self.stops.get(i, (0, 4095))
                registers[56:58] = u16(max(low, min(high, present + step)))
                pushing = not low <= present + step <= high  # into its stop: 260 mA, else 26 mA
                registers[69:71] = u16(40 if pushing else 4)
        super().handle(servo_id, instruction, params)


@pytest.fixture
def hal(params_file):
    os.environ['ROS_DOMAIN_ID'] = '77'  # a private ROS graph: never the one a running hand lives in
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    import rclpy
    from htn_control.hal_node import HandHal

    servos = MovingServos(IDS)
    for i in IDS:
        servos.registers[i][56:58] = u16(OPEN + 300)   # the fingers are NOT at "open" when we start
        servos.registers[i][42:44] = u16(OPEN)         # ... and the servos still hold an old goal
        servos.registers[i][40] = 1                    # ... with the torque left on by a crashed run
    rclpy.init(args=['--ros-args', '-p', 'backend:=feetech', '-p', f'serial_port:={servos.port}',
                      '-p', f'params_file:={params_file}'])
    node = HandHal()
    yield node, servos
    node.backend.close()
    node.destroy_node()
    rclpy.shutdown()


def position(servos, servo_id):
    return (from_u16(servos.registers[servo_id][56:58]) - OPEN) / (CLOSED - OPEN)


def test_start_up_takes_the_torque_off_then_holds_the_measured_pose(hal):
    node, servos = hal
    node.backend.read()
    assert all(servos.registers[i][40] == 0 for i in IDS), 'a leftover torque + old goal must not drive the hand'
    start = position(servos, 1)
    node.update()
    node.backend.read()
    assert all(servos.registers[i][40] == 1 for i in IDS)
    assert from_u16(servos.registers[1][42:44]) == OPEN + 300, 'the goal is where the finger is, not "open"'
    for _ in range(20):
        node.update()
    assert position(servos, 1) == pytest.approx(start, abs=0.01), 'and without a command nothing moves'


def test_a_finger_outside_its_travel_is_swept_in_not_snapped_to_the_edge(hal):
    node, servos = hal
    servos.registers[2][56:58] = u16(OPEN - 200)  # index beyond fully open
    node.update()
    node.backend.read()
    # held where it is, plus at most the first step of the sweep - not the 200 steps to the edge
    assert abs(from_u16(servos.registers[2][42:44]) - (OPEN - 200)) <= 30  # max_accel x dt^2 = 25 steps
    goals = []
    for _ in range(40):
        node.update()
        goals.append(from_u16(servos.registers[2][42:44]))
    assert goals[-1] == OPEN and max(abs(b - a) for a, b in zip(goals, goals[1:])) <= 85  # max_speed per cycle: 4.0 x 20 ms x 1024 steps


def test_a_blocked_finger_gets_the_low_torque_and_a_frozen_setpoint_and_comes_back(hal):
    node, servos = hal
    low, high = node.backend.hold_torque, node.backend.torque_limit
    assert low < high
    for _ in range(3):
        node.update()
    servos.stops[3] = (0, OPEN + 500)  # the middle finger meets something at ~0.49
    published = []
    node.blocked_pub.publish = lambda msg: published.append(list(msg.data))
    node.on_command(type('Msg', (), {'data': [0.3, 0.3, 1.0, 0.3, 0.3]})())
    for _ in range(80):
        node.update()
    assert node.contacts[2].state == BLOCKED
    assert servos.limits[3][-1] == low
    assert published == [[0.0, 0.0, 1.0, 0.0, 0.0]], '/hand/blocked: once, when the state changes'
    assert node.setpoint[2] == pytest.approx(position(servos, 3) + 0.03, abs=0.01), 'just past the obstacle'
    assert [c.state for i, c in enumerate(node.contacts) if i != 2] == [FREE] * 4, 'each finger alone'
    assert node.setpoint[0] == pytest.approx(0.3, abs=1e-6)

    node.on_command(type('Msg', (), {'data': [0.3, 0.3, 0.1, 0.3, 0.3]})())  # let go
    for _ in range(60):
        node.update()
    assert node.contacts[2].state == FREE and servos.limits[3][-1] == high
    assert published[-1] == [0.0] * 5
    assert position(servos, 3) == pytest.approx(0.1, abs=0.02)


def test_a_finger_stopped_just_before_its_target_is_blocked_by_the_current(hal):
    node, servos = hal
    assert node.contacts[1].blocked_current == 100
    for _ in range(3):
        node.update()
    servos.stops[2] = (0, OPEN + 500)  # the index meets something at ~0.49 ...
    node.on_command(type('Msg', (), {'data': [0.3, 0.52, 0.3, 0.3, 0.3]})())  # ... 0.03 before its target
    for _ in range(80):
        node.update()
    assert node.contacts[1].state == BLOCKED and servos.limits[2][-1] == node.backend.hold_torque


def test_the_obstacle_going_away_frees_the_finger_too(hal):
    node, servos = hal
    for _ in range(3):
        node.update()
    servos.stops[4] = (0, OPEN + 500)
    node.on_command(type('Msg', (), {'data': [0.3, 0.3, 0.3, 1.0, 0.3]})())
    for _ in range(80):
        node.update()
    assert node.contacts[3].state == BLOCKED
    del servos.stops[4]
    for _ in range(80):
        node.update()
    assert node.contacts[3].state == FREE and position(servos, 4) == pytest.approx(1.0, abs=0.02)


def test_the_hal_runs_the_calibrated_fingers_while_others_are_disabled(params_file, tmp_path):
    """Found with only the thumb calibrated: a disabled finger has no measured position, and the
    HAL waited for one for ever - so the thumb never got torque either."""
    import rclpy
    import yaml
    from htn_control.hal_node import HandHal

    params = yaml.safe_load(open(params_file))
    for finger in ('index', 'middle', 'ring', 'pinky'):
        params['servos'][finger]['enabled'] = False
    path = tmp_path / 'thumb_only.yaml'
    path.write_text(yaml.safe_dump(params))
    os.environ['ROS_DOMAIN_ID'] = '77'
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    servos = MovingServos(IDS)
    for i in IDS:
        servos.registers[i][56:58] = u16(OPEN)
    rclpy.init(args=['--ros-args', '-p', 'backend:=feetech', '-p', f'serial_port:={servos.port}',
                     '-p', f'params_file:={path}'])
    try:
        node = HandHal()
        node.on_command(type('Msg', (), {'data': [1.0] * 5})())
        for _ in range(80):
            node.update()
        node.backend.read()
        assert node.ready and position(servos, 1) == pytest.approx(1.0, abs=0.02), 'the thumb is driven'
        assert [servos.registers[i][40] for i in (2, 3, 4, 5)] == [0, 0, 0, 0], 'the others never get torque'
        assert [position(servos, i) for i in (2, 3, 4, 5)] == [0.0] * 4
        node.backend.close()
        node.destroy_node()
    finally:
        rclpy.shutdown()
