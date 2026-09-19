"""The calibration window's logic (Calibrator), on fake servos that move."""
import pytest
import yaml

from htn_control.calibrate_gui import TWITCH_STEPS, Calibrator
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
    linkage = {f: {'open_lock_rad': 0.49} for f in params['fingers']}
    yield Calibrator(bus, params, linkage, torque=150), servos
    bus.close()


def run(cal, servos, ticks=400):
    for _ in range(ticks):
        cal.tick(cal.positions()[cal.active] if cal.active else None)
        if cal.active is None or cal.step[cal.active] != 'testing':
            break


def torque(servos, servo_id):
    return servos.registers[servo_id][40]


def test_the_whole_flow_for_one_finger(rig):
    cal, servos = rig
    cal.select('index')
    cal.positions()
    assert torque(servos, 2) == 1 and from_u16(servos.registers[2][48:50]) == 150, 'low torque, this finger only'
    assert [torque(servos, i) for i in (1, 3, 4, 5)] == [0, 0, 0, 0]
    assert from_u16(servos.registers[2][42:44]) == 2100, 'selected = held where it is, not moved'

    cal.nudge(-100); cal.nudge(10)
    assert cal.goal == 2010
    cal.set_open()
    assert cal.step['index'] == 'which_way' and cal.goal == 2010 + TWITCH_STEPS
    cal.answer(curled_in=True)
    assert cal.result['index'] == (2010, 2010 + 836) and cal.goal == 2010 and cal.step['index'] == 'done'
    assert cal.lines()['index'] == '  index:  {id: 2, open_step: 2010, closed_step: 2846}'

    cal.start_test()
    goals = []
    for _ in range(400):
        cal.tick(cal.positions()['index'])
        goals.append(cal.goal)
        if cal.step['index'] != 'testing':
            break
    assert max(goals) == 2846 and goals[-1] == 2010 and 'fine' in cal.message
    assert max(abs(b - a) for a, b in zip(goals, goals[1:])) <= 6, 'slow: never more than a few steps per tick'


def test_a_mirrored_servo_closes_with_fewer_steps(rig):
    cal, _ = rig
    cal.select('ring')
    cal.set_open()
    cal.answer(curled_in=False)   # +80 steps opened it, so closing is the other way
    assert cal.result['ring'] == (2100, 2100 - 1024 * 0 - round(1.2523 * 4096 / 6.283185307179586))


def test_the_travel_test_stops_pushing_when_the_finger_is_blocked(rig):
    cal, servos = rig
    cal.select('middle'); cal.set_open(); cal.answer(True)
    servos.stops[3] = (0, 2100 + 300)
    cal.start_test()
    run(cal, servos)
    cal.positions()
    assert 'BLOCKED' in cal.message and cal.step['middle'] == 'done'
    assert abs(from_u16(servos.registers[3][42:44]) - 2400) <= 5, 'the goal came back to where the finger is'


def test_a_travel_that_would_cross_the_encoder_wrap_is_refused(rig):
    cal, servos = rig
    servos.registers[5][56:58] = u16(3600)
    cal.select('pinky'); cal.set_open(); cal.answer(True)
    assert 'encoder wrap' in cal.message and 'pinky' not in cal.result and cal.step['pinky'] == 'nudge'


def test_only_one_finger_has_torque_and_release_takes_it_off(rig):
    cal, servos = rig
    cal.select('thumb'); cal.select('index')
    cal.positions()
    assert torque(servos, 1) == 0 and torque(servos, 2) == 1
    cal.release(); cal.positions()
    assert torque(servos, 2) == 0 and cal.active is None


def test_moving_a_finished_finger_means_open_has_to_be_set_again(rig):
    cal, _ = rig
    cal.select('thumb'); cal.set_open(); cal.answer(True)
    cal.nudge(10)
    assert 'thumb' not in cal.result and cal.step['thumb'] == 'nudge'
