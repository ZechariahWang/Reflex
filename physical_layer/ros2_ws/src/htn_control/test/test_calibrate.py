"""The calibration window's logic (Calibrator), on fake servos that move."""
import pytest
import yaml

from htn_control.calibrate_gui import Calibrator
from htn_control.hal.feetech import FeetechBus, from_u16, u16
from test_contact import MovingServos

IDS = [1, 2, 3, 4, 5]


@pytest.fixture
def rig(params_file):
    servos = MovingServos(IDS, speed=40)
    for i in IDS:
        servos.registers[i][56:58] = u16(2100)
    bus = FeetechBus(servos.port, timeout=0.2)
    params = yaml.safe_load(open(params_file))
    linkage = {f: {'lock_rad': 1.47} for f in params['fingers']}  # binds at 84 deg = 958 steps
    yield Calibrator(bus, params, linkage, torque=150), servos
    bus.close()


def torque(servos, servo_id):
    return servos.registers[servo_id][40]


def test_set_open_set_closed_and_that_is_it(rig):
    cal, servos = rig
    cal.select('index')
    cal.positions()
    assert torque(servos, 2) == 1 and from_u16(servos.registers[2][48:50]) == 150, 'low torque, this finger only'
    assert [torque(servos, i) for i in (1, 3, 4, 5)] == [0, 0, 0, 0]
    assert from_u16(servos.registers[2][42:44]) == 2100, 'picked = held where it is, not moved'

    cal.nudge(-100); cal.nudge(10)
    cal.set_open()
    assert cal.result() == {}, 'one position is not a calibration yet'
    for _ in range(8):
        cal.nudge(100)
    cal.set_closed()
    assert cal.result() == {'index': (2010, 2810)}
    assert cal.lines()['index'] == '  index:  {id: 2, open_step: 2010, closed_step: 2810}'
    assert 'WARNING' not in cal.message


def test_either_order_and_a_mirrored_servo(rig):
    cal, _ = rig
    cal.select('ring')
    cal.set_closed()
    for _ in range(8):
        cal.nudge(100)
    cal.set_open()
    assert cal.result() == {'ring': (2900, 2100)}  # closed below open: a servo mounted the other way round


def test_a_span_past_where_the_linkage_binds_is_warned_about_not_refused(rig):
    cal, _ = rig
    cal.select('middle'); cal.set_open()
    for _ in range(10):
        cal.nudge(100)                      # 1000 steps = 88 deg of horn
    cal.set_closed()
    assert 'WARNING' in cal.message and 'binds at 84' in cal.message
    assert cal.result() == {'middle': (2100, 3100)}, 'it says so and does as told'


def test_the_travel_test_runs_there_and_back_slowly_and_stops_pushing_when_blocked(rig):
    cal, servos = rig
    cal.select('thumb'); cal.set_open()
    for _ in range(6):
        cal.nudge(100)
    cal.set_closed(); cal.toggle_test()
    goals = []
    for _ in range(600):
        cal.tick(cal.positions()['thumb'])
        goals.append(cal.goal)
        if not cal.testing:
            break
    assert min(goals) == 2100 and goals[-1] == 2100 and 'done' in cal.message
    assert max(abs(b - a) for a, b in zip(goals, goals[1:])) <= 6

    servos.stops[1] = (2100 + 250, 4095)     # now something is in the way of OPEN... of the way back
    for _ in range(3):
        cal.nudge(100)
    cal.toggle_test()
    for _ in range(600):
        cal.tick(cal.positions()['thumb'])
        if not cal.testing:
            break
    assert 'BLOCKED' in cal.message


def test_only_one_finger_has_torque_and_release_takes_it_off(rig):
    cal, servos = rig
    cal.select('thumb'); cal.select('index')
    cal.positions()
    assert torque(servos, 1) == 0 and torque(servos, 2) == 1
    cal.release(); cal.positions()
    assert torque(servos, 2) == 0 and cal.active is None
