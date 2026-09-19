import os
import threading
import time

import pytest
import rclpy.logging

from htn_control.hal.feetech import FeetechBus, FeetechError, from_u16, u16
from htn_control.hal.feetech_backend import FeetechBackend, to_norm, to_step
from htn_control.servo_tool import set_id


class FakeServos:
    """Servos on the master side of a pty; answers like the real bus."""

    def __init__(self, ids):
        self.registers = {i: bytearray(80) for i in ids}
        self.silent = set()
        self.corrupt = False
        self.requests = []
        self.master, slave = os.openpty()
        self.port = os.ttyname(slave)
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        buffer = b''
        while True:
            try:
                buffer += os.read(self.master, 256)
            except OSError:
                return
            while len(buffer) >= 4 and len(buffer) >= 4 + buffer[3]:
                packet, buffer = buffer[:4 + buffer[3]], buffer[4 + buffer[3]:]
                self.requests.append(packet)
                self.handle(packet[2], packet[4], packet[5:-1])

    def reply(self, servo_id, data=b''):
        if servo_id in self.silent or servo_id not in self.registers:
            return
        body = bytes([servo_id, len(data) + 2, 0]) + data
        checksum = ~sum(body) & 0xFF
        if self.corrupt:
            checksum ^= 0xFF
        os.write(self.master, b'\xff\xff' + body + bytes([checksum]))

    def store(self, servo_id, addr, data):
        registers = self.registers.get(servo_id)
        if registers is None:
            return
        if addr == 5 and registers[55] != 0:
            return  # EEPROM locked
        registers[addr:addr + len(data)] = data
        if addr == 5:
            self.registers[data[0]] = self.registers.pop(servo_id)

    def handle(self, servo_id, instruction, params):
        if instruction == 0x01:
            self.reply(servo_id)
        elif instruction == 0x02:
            addr, length = params
            if servo_id in self.registers:
                self.reply(servo_id, bytes(self.registers[servo_id][addr:addr + length]))
        elif instruction == 0x03:
            self.store(servo_id, params[0], params[1:])
            self.reply(servo_id if servo_id in self.registers else params[1])
        elif instruction == 0x83:
            addr, length = params[0], params[1]
            for i in range(2, len(params), length + 1):
                self.store(params[i], addr, params[i + 1:i + 1 + length])
        elif instruction == 0x82:
            addr, length = params[0], params[1]
            for i in params[2:]:
                if i in self.registers:
                    self.reply(i, bytes(self.registers[i][addr:addr + length]))


@pytest.fixture
def servos():
    return FakeServos([1, 2, 3])


@pytest.fixture
def bus(servos):
    bus = FeetechBus(servos.port, timeout=0.2)
    yield bus
    bus.close()


def test_ping_packet_matches_known_bytes(servos, bus):
    assert bus.ping(1)
    assert servos.requests[0] == bytes.fromhex('ffff010201fb')


def test_ping_absent_servo_is_false(bus):
    assert not bus.ping(9)


def test_write_then_read_is_little_endian(servos, bus):
    bus.write(1, 42, u16(0x0123))
    assert servos.registers[1][42:44] == b'\x23\x01'
    assert from_u16(bus.read(1, 42, 2)) == 0x0123


def test_corrupt_checksum_raises(servos, bus):
    servos.corrupt = True
    with pytest.raises(FeetechError):
        bus.read(1, 56, 2)


def test_read_timeout_raises(servos, bus):
    servos.silent.add(1)
    with pytest.raises(FeetechError):
        bus.read(1, 56, 2)


def test_sync_write_reaches_each_servo(servos, bus):
    bus.sync_write(42, {1: u16(100), 2: u16(2000), 3: u16(4095)})
    bus.ping(1)  # a sync write has no reply; wait for the bus to drain
    assert [from_u16(servos.registers[i][42:44]) for i in (1, 2, 3)] == [100, 2000, 4095]


def test_sync_read_omits_silent_servo(servos, bus):
    for i in (1, 2, 3):
        servos.registers[i][56:58] = u16(1000 + i)
    servos.silent.add(2)
    result = bus.sync_read(56, 2, [1, 2, 3])
    assert {i: from_u16(d) for i, d in result.items()} == {1: 1001, 3: 1003}


def test_set_id_changes_id_and_locks_eeprom(servos, bus):
    servos.registers[1][55] = 1
    set_id(bus, 1, 7)
    assert 7 in servos.registers and 1 not in servos.registers
    assert servos.registers[7][55] == 1


def test_set_id_refuses_id_in_use(servos, bus):
    with pytest.raises(ValueError):
        set_id(bus, 1, 2)
    assert 1 in servos.registers


def test_step_mapping_round_trips_with_mirrored_servo():
    assert to_step(0.0, 3000, 1000) == 3000
    assert to_step(1.0, 3000, 1000) == 1000
    assert to_step(0.25, 3000, 1000) == 2500
    assert to_norm(2500, 3000, 1000) == pytest.approx(0.25)
    assert to_norm(to_step(0.6, 1000, 3000), 1000, 3000) == pytest.approx(0.6, abs=1e-3)


class FakeNode:
    def __init__(self, **params):
        self.params = params
        # One logger object per node, as in rclpy: its call-site checks reject
        # some mixes of plain and throttled calls
        self.logger = rclpy.logging.get_logger('test_feetech')

    def declare_parameter(self, name, default):
        return type('Parameter', (), {'value': self.params.get(name, default)})

    def get_logger(self):
        return self.logger


HAND_PARAMS = {'servos': {
    'torque_limit': 300,
    **{finger: {'id': n, 'open_step': 1000, 'closed_step': 3000}
       for n, finger in enumerate(['thumb', 'index', 'middle', 'ring', 'pinky'], start=1)}}}


def test_backend_refuses_absent_servo_by_default(servos):
    with pytest.raises(RuntimeError):
        FeetechBackend(FakeNode(serial_port=servos.port), HAND_PARAMS)


def test_backend_runs_with_absent_servos_when_allowed(servos):
    node = FakeNode(serial_port=servos.port, require_all_servos=False)
    backend = FeetechBackend(node, HAND_PARAMS)
    assert backend.present == [True, True, True, False, False]
    # No torque from the constructor: the HAL turns it on once it knows the measured pose
    assert servos.registers[1][40] == 0 and from_u16(servos.registers[1][48:50]) == 300
    backend.set_torque(True, hold=[0.0] * 5)
    backend.read()
    assert servos.registers[1][40] == 1

    servos.registers[1][56:58] = u16(2000)
    backend.write([0.5, 0.0, 0.0, 0.0, 0.25])
    state = backend.read()
    assert from_u16(servos.registers[1][42:44]) == 2000
    assert state[0] == pytest.approx(0.5)
    assert state[4] == pytest.approx(0.25)  # absent finger reports its command
    servos.silent.add(2)
    assert backend.read()[1] == state[1]  # no answer: warning, last value kept
    backend.close()
    deadline = time.time() + 1.0  # torque-off has no reply to wait for
    while servos.registers[1][40] and time.time() < deadline:
        time.sleep(0.01)
    assert servos.registers[1][40] == 0


def test_calibration_lines_replace_only_their_own_lines():
    from htn_control.servo_tool import rewrite_yaml, yaml_line
    text = ('servos:\n  torque_limit: 300    # keep me\n'
            '  thumb:  {id: 1, open_step: 2048, closed_step: 2884}\n'
            '  index:  {id: 2, open_step: 2048, closed_step: 2884}   # old\n')
    out = rewrite_yaml(text, {'index': yaml_line('index', 2, 1990, 1154)})
    assert '  index:  {id: 2, open_step: 1990, closed_step: 1154}\n' in out
    assert '  thumb:  {id: 1, open_step: 2048, closed_step: 2884}\n' in out and 'keep me' in out
    with pytest.raises(ValueError):
        rewrite_yaml(text, {'pinky': yaml_line('pinky', 5, 1, 2)})


def test_scan_reports_a_servo_that_pings_but_cannot_be_read(servos, bus, capsys):
    from htn_control.servo_tool import scan
    real_read = bus.read
    bus.read = lambda servo_id, addr, length: (_ for _ in ()).throw(FeetechError('bad reply checksum')) \
        if servo_id == 2 else real_read(servo_id, addr, length)
    scan(bus, ids=range(1, 5))
    out = capsys.readouterr().out
    assert 'id 1: position' in out and 'id 3: position' in out and 'several servos on this id' in out
