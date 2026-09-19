"""Passive (backdrive) mode: torque off, encoders still read, no jump on the way back."""
import os

import pytest

from htn_control.hal import feetech
from htn_control.hal.feetech import from_u16, u16
from htn_control.hal.feetech_backend import FeetechBackend
from test_feetech import HAND_PARAMS, FakeNode, FakeServos

IDS = [1, 2, 3, 4, 5]
OPEN, CLOSED = 2048, 3072  # hand_params.yaml


def writes(servos, addr):
    """(position in the request log, {id: value}) of every sync write to `addr`."""
    found = []
    for n, packet in enumerate(servos.requests):
        if packet[4] == feetech.SYNC_WRITE and packet[5] == addr:
            length, body = packet[6], packet[7:-1]
            found.append((n, {body[i]: bytes(body[i + 1:i + 1 + length])
                              for i in range(0, len(body), length + 1)}))
    return found


def test_torque_comes_back_on_the_measured_pose_goal_first():
    servos = FakeServos(IDS)
    backend = FeetechBackend(FakeNode(serial_port=servos.port), HAND_PARAMS)
    backend.write([0.0] * 5)

    backend.set_torque(False)
    assert all(servos.registers[i][40] == 0 for i in IDS)

    hold = [0.5, 0.25, 0.0, 1.0, 0.75]
    del servos.requests[:]
    backend.set_torque(True, hold=hold)
    backend.read()  # a request with a reply: everything before it has been handled
    goal, torque = writes(servos, feetech.ADDR_GOAL_POSITION), writes(servos, feetech.ADDR_TORQUE_ENABLE)
    assert len(goal) == 1 and len(torque) == 1
    assert goal[0][0] < torque[0][0], 'the goal must be on the bus before the torque'
    assert from_u16(goal[0][1][1]) == 2000 and from_u16(goal[0][1][4]) == 3000  # 1000..3000 in HAND_PARAMS
    assert all(value == b'\x01' for value in torque[0][1].values())
    backend.close()


@pytest.fixture
def hal():
    # A private ROS graph: never the one a running sim or hand lives in
    os.environ['ROS_DOMAIN_ID'] = '77'
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    import rclpy
    from htn_control.hal_node import HandHal

    servos = FakeServos(IDS)
    for i in IDS:
        servos.registers[i][56:58] = u16(OPEN)
    rclpy.init(args=['--ros-args', '-p', 'backend:=feetech', '-p', f'serial_port:={servos.port}'])
    node = HandHal()
    yield node, servos
    node.backend.close()
    node.destroy_node()
    rclpy.shutdown()


def test_hal_follows_backdriven_fingers_and_holds_them_afterwards(hal):
    node, servos = hal
    node.on_command(type('Msg', (), {'data': [1.0] * 5})())
    node.update()
    assert node.target == [1.0] * 5

    node.set_passive(True)
    assert all(servos.registers[i][40] == 0 for i in IDS)

    # A person closes the index finger half way; nothing may be commanded meanwhile
    servos.registers[2][56:58] = u16((OPEN + CLOSED) // 2)
    node.on_command(type('Msg', (), {'data': [0.0] * 5})())
    del servos.requests[:]
    node.update()
    assert writes(servos, feetech.ADDR_GOAL_POSITION) == []
    assert node.setpoint == pytest.approx([0.0, 0.5, 0.0, 0.0, 0.0], abs=1e-3)
    assert node.target == node.setpoint  # the old "close everything" is forgotten

    del servos.requests[:]
    node.set_passive(False)
    node.backend.read()
    goal, torque = writes(servos, feetech.ADDR_GOAL_POSITION), writes(servos, feetech.ADDR_TORQUE_ENABLE)
    assert goal[0][0] < torque[0][0]
    assert from_u16(goal[0][1][2]) == (OPEN + CLOSED) // 2 and from_u16(goal[0][1][1]) == OPEN
    assert all(servos.registers[i][40] == 1 for i in IDS)

    node.update()  # active again: holds the pose, does not run to the pre-passive target
    assert from_u16(servos.registers[2][42:44]) == (OPEN + CLOSED) // 2


def test_a_finger_pushed_past_its_range_is_held_at_the_limit(hal):
    node, servos = hal
    node.set_passive(True)
    servos.registers[1][56:58] = u16(OPEN - 80)  # beyond fully open
    node.update()
    assert node.setpoint[0] == 0.0
    node.set_passive(False)
    assert from_u16(servos.registers[1][42:44]) == OPEN
