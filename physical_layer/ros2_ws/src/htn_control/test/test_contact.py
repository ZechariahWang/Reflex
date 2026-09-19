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
    return ContactDetector(blocked_error=0.06, blocked_motion=0.004, blocked_cycles=10, hold_lead=0.03)


def test_a_slow_servo_in_free_motion_is_not_blocked():
    contact, measured = detector(), 0.0
    for cycle in range(100):  # trails the setpoint by 0.2, but it moves
        measured += 0.005
        assert contact.update(measured + 0.2, measured, 1.0) == FREE


def test_far_from_the_setpoint_and_not_moving_is_blocked_then_held_just_past_the_obstacle():
    contact = detector()
    states = [contact.update(0.6, 0.30, 1.0) for _ in range(12)]
    assert states[:10] == [FREE] * 10 and states[-1] == BLOCKED  # needs the full window first
    assert contact.direction == 1.0 and contact.hold_setpoint() == pytest.approx(0.33)


def test_at_rest_on_the_target_is_not_blocked():
    contact = detector()
    assert all(contact.update(0.5, 0.49, 0.5) == FREE for _ in range(50))


@pytest.mark.parametrize('direction', [1.0, -1.0])
def test_released_by_a_command_the_other_way_or_by_the_obstacle_going_away(direction):
    blocked_at, target = 0.5, 0.5 + 0.5 * direction
    contact = detector()
    for _ in range(12):
        contact.update(blocked_at + 0.2 * direction, blocked_at, target)
    assert contact.state == BLOCKED and contact.direction == direction
    assert contact.update(contact.hold_setpoint(), blocked_at, target) == BLOCKED  # still pushing: stays
    assert contact.update(contact.hold_setpoint(), blocked_at, blocked_at - 0.3 * direction) == FREE

    for _ in range(12):
        contact.update(blocked_at + 0.2 * direction, blocked_at, target)
    assert contact.state == BLOCKED
    assert contact.update(contact.hold_setpoint(), blocked_at + 0.02 * direction, target) == FREE  # it moves again


def test_current_above_the_threshold_blocks_where_the_encoder_rule_is_blind():
    contact = ContactDetector(0.06, 0.004, 10, 0.03, blocked_current=100, blocked_excess=150)
    # 0.03 from the setpoint (< blocked_error) and still creeping: the encoder rule never fires
    states = [contact.update(0.53 + 0.003 * n, 0.50 + 0.003 * n, 0.6, current=150) for n in range(3)]
    assert states == [FREE, FREE, BLOCKED] and contact.direction == 1.0


def test_one_huge_cycle_blocks_at_once():
    contact = ContactDetector(0.06, 0.004, 10, 0.03, blocked_current=100, blocked_excess=150)
    assert contact.update(0.52, 0.50, 0.6, current=90) == FREE
    assert contact.update(0.52, 0.50, 0.6, current=260) == BLOCKED


def test_the_peak_of_a_free_start_drains_away_and_no_current_reading_does_not_block():
    contact = ContactDetector(0.06, 0.004, 10, 0.03, blocked_current=100, blocked_excess=150)
    # the middle finger on the hand, a free start, again and again: 34 mA over, then well below
    for current in [91, 110, 104, 110, 110, 78, 65] * 10 + [None] * 10:
        assert contact.update(0.52, 0.50, 0.6, current=current) == FREE


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
    assert abs(from_u16(servos.registers[2][42:44]) - (OPEN - 200)) <= 10
    goals = []
    for _ in range(40):
        node.update()
        goals.append(from_u16(servos.registers[2][42:44]))
    assert goals[-1] == OPEN and max(abs(b - a) for a, b in zip(goals, goals[1:])) <= 45  # max_speed per cycle


def test_a_blocked_finger_gets_the_low_torque_and_a_frozen_setpoint_and_comes_back(hal):
    node, servos = hal
    low, high = node.backend.hold_torque, node.backend.torque_limit
    assert low < high
    for _ in range(3):
        node.update()
    servos.stops[3] = (0, OPEN + 500)  # the middle finger meets something at ~0.49
    node.on_command(type('Msg', (), {'data': [0.3, 0.3, 1.0, 0.3, 0.3]})())
    for _ in range(80):
        node.update()
    assert node.contacts[2].state == BLOCKED
    assert servos.limits[3][-1] == low
    assert node.setpoint[2] == pytest.approx(position(servos, 3) + 0.03, abs=0.01), 'frozen just past the obstacle'
    assert [c.state for i, c in enumerate(node.contacts) if i != 2] == [FREE] * 4, 'each finger alone'
    assert node.setpoint[0] == pytest.approx(0.3, abs=1e-6)

    node.on_command(type('Msg', (), {'data': [0.3, 0.3, 0.1, 0.3, 0.3]})())  # let go
    for _ in range(60):
        node.update()
    assert node.contacts[2].state == FREE and servos.limits[3][-1] == high
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
