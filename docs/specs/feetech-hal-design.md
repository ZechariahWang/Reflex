# Feetech servo backend for the HAL

Driver for the real hand: 5 Feetech ST series serial bus servos behind a
Waveshare Bus Servo Adapter (A). Status: implemented; scan, jog and feedback reads verified on one ST servo.
Date: 2026-09-19. This closes open question 6 of `../system-design.md`.

## Hardware facts

- The adapter is a CH343 USB to half-duplex UART bridge (`1a86:55d3`,
  `/dev/ttyACM0`). It has no MCU and no protocol of its own. The adapter
  switches the bus direction in hardware.
- The computer speaks the Feetech protocol directly to the servos, at
  1 000 000 baud (factory default of the ST series).
- ST series: 4096 steps per 360 degrees, little-endian 2-byte registers,
  position feedback. The servo has no command timeout.
- "253 servos" is the ID range of the bus (0..253; 254 is broadcast). The
  driver addresses servos by ID. The hand uses 5.
- New ST servos all have ID 1. Two servos with the same ID cannot share the
  bus.

## Scope

In: the protocol module, the HAL backend, a command-line servo tool, the YAML
and launch changes, removal of `SerialBackend`.

Out: the command watchdog and the emergency open of `../system-design.md`
(Safety). These belong in `hal_node.py` and apply to all backends. SC series
support (big-endian, 1024 steps) is also out.

## Components

All paths are in `physical_layer/ros2_ws/src/htn_control/htn_control/`.

### `hal/feetech.py` - protocol

No ROS import. One class:

```python
class FeetechBus:
    def __init__(self, port, baud=1_000_000, timeout=0.02): ...
    def ping(self, servo_id) -> bool
    def read(self, servo_id, addr, length) -> bytes
    def write(self, servo_id, addr, data: bytes) -> None
    def sync_write(self, addr, data_by_id: dict[int, bytes]) -> None
    def sync_read(self, addr, length, ids) -> dict[int, bytes]
    def close(self) -> None
```

- Packet: `FF FF id len instr params... chk`, with `len = len(params) + 2` and
  `chk = ~(id + len + instr + sum(params)) & 0xFF`.
- Status reply: `FF FF id len error params... chk`.
- Instructions: ping `0x01`, read `0x02`, write `0x03`, sync read `0x82`, sync
  write `0x83`. Sync instructions go to ID `0xFE`. A sync write has no reply.
  A sync read gets one status packet per servo, in the order of the ID list.
- The input buffer is cleared before each request, so a late reply cannot be
  read as the answer to the next request.
- Errors: `FeetechError` for a timeout, a bad header, a bad checksum or a reply
  from the wrong ID. `sync_read` omits a servo that does not answer; it does
  not raise. `ping` returns `False` on timeout.
- The error byte of the last status packet of each servo is kept in
  `bus.errors: dict[int, int]` (bit 0 voltage, bit 2 temperature, bit 3
  current, bit 5 overload).
- Helpers `u16(value) -> bytes` and `from_u16(bytes) -> int`, little-endian.

Registers used (ST series memory table):

| Address | Name | Size | Area |
|---|---|---|---|
| 5 | ID | 1 | EEPROM |
| 40 | Torque enable | 1 | RAM |
| 41 | Acceleration | 1 | RAM |
| 42 | Goal position | 2 | RAM |
| 48 | Torque limit (0..1000) | 2 | RAM |
| 55 | EEPROM lock (0 = unlocked) | 1 | RAM |
| 56 | Present position | 2 | RAM |

### `hal/feetech_backend.py` - HAL backend

`FeetechBackend(HandBackend)`, registered as `'feetech'` in `hal/__init__.py`.

- ROS parameters: `serial_port` (default `/dev/ttyACM0`), `baud_rate`
  (default 1000000), `servo_acceleration` (default 50, unit 100 steps/s^2,
  0 = no limit). `require_all_servos` (default true); false is for bench
  tests: an absent servo gives a warning, gets no commands and reports its
  command as its state.
- Start: ping each of the 5 IDs. If one is absent, raise with the finger name
  and the ID. Then write the torque limit and the acceleration, and enable
  torque.
- `write(positions)`: `step = open_step + p * (closed_step - open_step)`,
  rounded, then one sync write to register 42. The goal speed stays at its
  default (maximum); the HAL rate limit (`max_speed`) sets the speed.
- `read()`: one sync read of register 56, then
  `p = (step - open_step) / (closed_step - open_step)`. A finger with no
  answer keeps its last value, with a throttled warning. Returns `None` until
  each finger has answered one time. A non-zero servo error byte gives a
  throttled warning with the finger name.
- `close()`: torque off for all servos, then close the port.
- Bus time per 50 Hz cycle at 1 Mbaud is approximately 2 ms plus USB latency,
  which fits in the 20 ms period.

### `servo_tool.py` - setup tool

Console script `servo_tool` (`ros2 run htn_control servo_tool ...`). Uses
`FeetechBus` only. Arguments `--port` and `--baud`.

- `scan`: ping IDs 0..253, print the IDs that answer and their position.
- `set-id <old> <new>`: unlock the EEPROM (55 = 0), write register 5, lock
  (55 = 1), then ping the new ID. Refuses if `<new>` already answers.
  Connect one servo at a time for this.
- `jog <id>`: keyboard jog for calibration. The mechanism cannot be backdriven
  and the wearer cannot move their fingers, so calibration by hand is not
  possible. The tool sets a low torque limit (default 200, `--torque`),
  enables torque at the present position, then moves in steps of 10 (`j`/`k`)
  or 100 (`J`/`K`) and prints the step value. `q` turns the torque off and
  exits. The operator records the open and closed values in the YAML.

### Configuration

`htn_description/config/hand_params.yaml`, replaces the `servos` section:

```yaml
# Real servos (HAL feetech backend only). Steps are 0..4095 (4096 per turn).
# closed_step < open_step is correct for a mirrored servo. Find the values
# with `servo_tool jog`.
servos:
  torque_limit: 300    # 0..1000, fraction of stall torque, set at each start
  thumb:  {id: 1, open_step: 2048, closed_step: 3072}
  index:  {id: 2, open_step: 2048, closed_step: 3072}
  middle: {id: 3, open_step: 2048, closed_step: 3072}
  ring:   {id: 4, open_step: 2048, closed_step: 3072}
  pinky:  {id: 5, open_step: 2048, closed_step: 3072}
```

`hardware.launch.py`: backend `feetech`, `baud_rate` default `1000000`.

### Removal

`hal/serial_backend.py` and its `'serial'` entry are deleted. No firmware
exists for its ASCII protocol and the adapter makes an MCU unnecessary. The
related text in `CLAUDE.md`, `physical_layer/CLAUDE.md` and `../system-design.md`
is updated in the same change.

## Safety

- The torque limit (register 48) is the force limit of `../system-design.md`. It
  is RAM, so the backend writes it at each start, before torque is enabled.
  The overload protection of the servo stays at its factory setting.
- The clamp and the rate limit of `hal_node.py` stay as they are.
- Known limit: if the HAL process stops without `close()`, the servos hold the
  last goal, because the servo has no command timeout. Only a power switch
  can fix this. The wearer must be able to reach it.

## Setup on the machine

- The port belongs to group `uucp` (Arch) or `dialout` (Ubuntu). The host user
  must be in that group, and the distrobox must keep it
  (`--group-add keep-groups`).
- `pyserial` comes from `python3-serial` (`<exec_depend>` in `package.xml`),
  installed in the ROS container.

## Tests (TDD)

`htn_control/test/test_feetech.py`, plain pytest, no ROS and no hardware. A
fake servo bus on a pty (`os.openpty`) answers the requests from a small
register map per ID. The tests are written first and must fail before the
implementation exists.

- Ping packet bytes and checksum match a known-good example
  (`FF FF 01 02 01 FB`).
- `read` and `write` round-trip a 2-byte register, little-endian.
- A corrupted checksum raises `FeetechError`. No answer raises on `read` and
  gives `False` on `ping`.
- `sync_write` puts the correct value in each fake servo. `sync_read` returns
  all servos that answer and omits one that does not.
- `set-id` changes the ID and leaves the EEPROM locked.
- Backend mapping: normalized to step and back, with a mirrored servo. The
  mapping is a pure function, so the test needs no ROS node.

Hardware check, in this order: `servo_tool scan`; `set-id` for each servo;
`jog` for each finger and record the YAML values; `hardware.launch.py` with
teleop; 10 minutes of motion with no `FeetechError` in the log.
