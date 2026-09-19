from htn_control.hal.base import HandBackend
from htn_control.hand_config import FINGERS


class SerialBackend(HandBackend):
    """Real servos behind a microcontroller on a serial port.

    Wire protocol (ASCII, one line per message), to be mirrored by the firmware:
        laptop -> MCU   "S <d0> <d1> <d2> <d3> <d4>\\n"   servo targets, degrees
        MCU -> laptop   "P <d0> <d1> <d2> <d3> <d4>\\n"   measured, degrees (optional)
    in FINGERS order. The MCU should relax the servos if "S" lines stop coming.

    Per-servo calibration comes from the `servos` section of hand_params.yaml:
    open_deg / closed_deg are the servo angles at finger fully open / closed
    (closed_deg < open_deg is fine for a servo mounted the other way round).
    """

    def __init__(self, node, hand_params):
        super().__init__(node, hand_params)
        import serial  # only needed on the real hand

        servos = hand_params['servos']
        self.open_deg = [servos[f]['open_deg'] for f in FINGERS]
        self.closed_deg = [servos[f]['closed_deg'] for f in FINGERS]
        self.measured = None

        port = node.declare_parameter('serial_port', '/dev/ttyACM0').value
        baud = node.declare_parameter('baud_rate', 115200).value
        self.serial = serial.Serial(port, baud, timeout=0)
        self.rx_buffer = b''
        node.get_logger().info(f'Serial backend on {port} @ {baud}')

    def write(self, positions):
        degrees = [o + p * (c - o)
                   for p, o, c in zip(positions, self.open_deg, self.closed_deg)]
        line = 'S ' + ' '.join(f'{d:.1f}' for d in degrees) + '\n'
        self.serial.write(line.encode())

    def read(self):
        self.rx_buffer += self.serial.read(self.serial.in_waiting or 0)
        *lines, self.rx_buffer = self.rx_buffer.split(b'\n')
        for line in lines:
            parts = line.decode(errors='ignore').split()
            if len(parts) == 1 + len(FINGERS) and parts[0] == 'P':
                try:
                    degrees = [float(v) for v in parts[1:]]
                except ValueError:
                    continue
                self.measured = [(d - o) / (c - o) for d, o, c
                                 in zip(degrees, self.open_deg, self.closed_deg)]
        return self.measured

    def close(self):
        self.serial.close()
