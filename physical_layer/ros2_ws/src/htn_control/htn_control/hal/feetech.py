"""Feetech ST series serial bus protocol (half-duplex UART, little-endian).

Request  FF FF id len instr params... chk
Reply    FF FF id len error params... chk
with len = len(params) + 2 and chk = ~(id + len + instr/error + params) & 0xFF.
"""

PING, READ, WRITE, SYNC_READ, SYNC_WRITE = 0x01, 0x02, 0x03, 0x82, 0x83
BROADCAST = 0xFE

# ST series memory table
ADDR_ID = 5
ADDR_TORQUE_ENABLE = 40
ADDR_ACCELERATION = 41
ADDR_GOAL_POSITION = 42
ADDR_TORQUE_LIMIT = 48
ADDR_LOCK = 55
ADDR_PRESENT_POSITION = 56
ADDR_PRESENT_LOAD = 60      # drive duty in 0.1 %, bit 10 = direction: the loop's output, not a measurement
ADDR_PRESENT_CURRENT = 69   # measured motor current, bit 15 = direction
CURRENT_MA = 6.5            # mA per count of ADDR_PRESENT_CURRENT


class FeetechError(Exception):
    pass


def u16(value):
    return int(value).to_bytes(2, 'little')


def from_u16(data):
    return int.from_bytes(data, 'little')


def from_sign_magnitude(data, sign_bit):
    """Load and current: magnitude with a direction bit, not two's complement."""
    value = from_u16(data)
    return -(value & ~(1 << sign_bit)) if value >> sign_bit & 1 else value


class FeetechBus:

    def __init__(self, port, baud=1_000_000, timeout=0.02):
        import serial  # only needed on the real hand
        self.serial = serial.Serial(port, baud, timeout=timeout)
        # Error byte of the last reply of each servo (bit 0 voltage,
        # bit 2 temperature, bit 3 current, bit 5 overload)
        self.errors = {}

    def close(self):
        self.serial.close()

    def send(self, servo_id, instruction, params=b''):
        body = bytes([servo_id, len(params) + 2, instruction]) + bytes(params)
        # A late reply must not be read as the answer to this request
        self.serial.reset_input_buffer()
        self.serial.write(b'\xff\xff' + body + bytes([~sum(body) & 0xFF]))

    def receive(self, servo_id=None):
        """Read one reply, return (id, data). servo_id=None accepts any servo."""
        header = self.serial.read(4)
        if len(header) < 4:
            raise FeetechError(f'servo {servo_id}: no reply')
        if header[:2] != b'\xff\xff' or servo_id not in (None, header[2]):
            raise FeetechError(f'servo {servo_id}: bad reply header {header.hex()}')
        rest = self.serial.read(header[3])
        if len(rest) < header[3] or ~sum(header[2:] + rest[:-1]) & 0xFF != rest[-1]:
            raise FeetechError(f'servo {header[2]}: bad reply checksum or length')
        self.errors[header[2]] = rest[0]
        return header[2], rest[1:-1]

    def ping(self, servo_id):
        self.send(servo_id, PING)
        try:
            self.receive(servo_id)
        except FeetechError:
            return False
        return True

    def read(self, servo_id, addr, length):
        self.send(servo_id, READ, [addr, length])
        _, data = self.receive(servo_id)
        if len(data) != length:
            raise FeetechError(f'servo {servo_id}: got {len(data)} bytes, expected {length}')
        return data

    def write(self, servo_id, addr, data):
        self.send(servo_id, WRITE, bytes([addr]) + bytes(data))
        self.receive(servo_id)

    def sync_write(self, addr, data_by_id):
        length = len(next(iter(data_by_id.values())))
        params = bytes([addr, length])
        for servo_id, data in data_by_id.items():
            params += bytes([servo_id]) + bytes(data)
        self.send(BROADCAST, SYNC_WRITE, params)

    def sync_read(self, addr, length, ids):
        """Return {id: data}; a servo that does not answer correctly is absent."""
        self.send(BROADCAST, SYNC_READ, bytes([addr, length]) + bytes(ids))
        result = {}
        for _ in ids:
            try:
                servo_id, data = self.receive()
            except FeetechError:
                break
            if servo_id in ids and len(data) == length:
                result[servo_id] = data
        return result
