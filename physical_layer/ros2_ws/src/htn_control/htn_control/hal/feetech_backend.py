from htn_control.hal import feetech
from htn_control.hal.base import HandBackend
from htn_control.hal.feetech import FeetechBus, from_sign_magnitude, from_u16, u16
from htn_control.hand_config import FINGERS


def to_step(position, open_step, closed_step):
    return round(open_step + position * (closed_step - open_step))


def to_norm(step, open_step, closed_step):
    return (step - open_step) / (closed_step - open_step)


def clamp_step(step):
    return min(max(step, 0), 4095)


class FeetechBackend(HandBackend):
    """Feetech ST series bus servos behind a USB bus adapter (no MCU).

    Per-servo id and calibration come from the `servos` section of
    hand_params.yaml: open_step / closed_step are the servo positions
    (0..4095) at finger fully open / closed; closed_step < open_step is fine
    for a servo mounted the other way round.
    """

    def __init__(self, node, hand_params):
        super().__init__(node, hand_params)
        servos = hand_params['servos']
        self.ids = [servos[f]['id'] for f in FINGERS]
        self.open_step = [servos[f]['open_step'] for f in FINGERS]
        self.closed_step = [servos[f]['closed_step'] for f in FINGERS]
        self.measured = [None] * len(FINGERS)
        self.torque_limit = servos['torque_limit']
        self.hold_torque = servos.get('hold_torque', self.torque_limit)

        port = node.declare_parameter('serial_port', '/dev/ttyACM0').value
        baud = node.declare_parameter('baud_rate', 1_000_000).value
        # Unit 100 steps/s^2, 0 = no limit
        # The servo's own ramp, in 100 steps/s^2 (254 = the most). The HAL's sweep already eases every
        # move in and out; at 50 the servo took another 0.3 s to reach its speed, and coasted as long
        # past a goal that stopped - a quick key stroke was a wobble, not a stroke.
        acceleration = node.declare_parameter('servo_acceleration', 254).value
        # False is for bench tests with part of the servos; the hand needs all 5
        require_all = node.declare_parameter('require_all_servos', True).value
        self.bus = FeetechBus(port, baud)

        # `enabled: false` = not calibrated yet: that finger never gets torque or a goal, whatever
        # is commanded. It is treated like a servo that is not there (it reports its command).
        self.enabled = [servos[f].get('enabled', True) for f in FINGERS]
        self.present = [enabled and self.bus.ping(i) for i, enabled in zip(self.ids, self.enabled)]
        for finger, servo_id, present, enabled in zip(FINGERS, self.ids, self.present, self.enabled):
            if present:
                continue
            if not enabled:
                node.get_logger().warning(f'{finger} servo (id {servo_id}) is disabled in hand_params.yaml '
                                          f'(not calibrated): it will not be driven')
                continue
            if require_all:
                self.bus.close()
                raise RuntimeError(f'No answer from {finger} servo (id {servo_id}) on {port}')
            node.get_logger().warning(f'No {finger} servo (id {servo_id}), running without it')
        self.active_ids = [i for i, present in zip(self.ids, self.present) if present]
        # A finger without a servo reports its command. Before the first command that is "open":
        # it must not stay None, or the HAL (which drives nothing before it has a whole measured
        # pose) would wait for ever and the fingers that ARE there would never get torque.
        self.measured = [None if present else 0.0 for present in self.present]
        self.current = [0.0] * len(FINGERS)  # mA, absolute
        # The torque limit is RAM: set it before the servos get torque. The torque itself stays
        # OFF here: the HAL turns it on through set_torque() once it knows the measured pose, with
        # that pose as the goal. Enabling it here drove every finger to whatever goal the servo
        # still held, at full torque, before anything had looked at where the fingers are.
        for servo_id in self.active_ids:
            self.bus.write(servo_id, feetech.ADDR_TORQUE_ENABLE, [0])
            self.bus.write(servo_id, feetech.ADDR_TORQUE_LIMIT, u16(self.torque_limit))
            self.bus.write(servo_id, feetech.ADDR_ACCELERATION, [acceleration])
        node.get_logger().info(f'Feetech backend on {port} @ {baud}, ids {self.active_ids}')

    has_torque_limit = True

    def set_torque_limit(self, finger, blocked):
        if self.present[finger]:
            self.bus.write(self.ids[finger], feetech.ADDR_TORQUE_LIMIT,
                           u16(self.hold_torque if blocked else self.torque_limit))

    def write(self, positions):
        for n, position in enumerate(positions):
            if not self.present[n]:
                self.measured[n] = position
        self.bus.sync_write(feetech.ADDR_GOAL_POSITION, {
            i: u16(clamp_step(to_step(p, o, c)))  # a pose outside 0..1 is legal (start-up), the encoder range is not
            for i, p, o, c, present in zip(self.ids, positions, self.open_step,
                                           self.closed_step, self.present) if present})

    def read(self):
        # position .. current is one block (15 bytes), like the vendor SDK reads it
        replies = self.bus.sync_read(feetech.ADDR_PRESENT_POSITION, 15, self.active_ids)
        log = self.node.get_logger()
        for n, (finger, servo_id) in enumerate(zip(FINGERS, self.ids)):
            if not self.present[n]:
                continue
            if servo_id not in replies:
                log.warning(f'No position from {finger} servo (id {servo_id})',
                            throttle_duration_sec=2.0)
                continue
            self.measured[n] = to_norm(
                from_u16(replies[servo_id][:2]), self.open_step[n], self.closed_step[n])
            self.current[n] = abs(from_sign_magnitude(replies[servo_id][13:15], 15)) * feetech.CURRENT_MA
            if self.bus.errors.get(servo_id):
                log.warning(f'{finger} servo (id {servo_id}) reports error '
                            f'0x{self.bus.errors[servo_id]:02x}', throttle_duration_sec=2.0)
        return None if None in self.measured else list(self.measured)

    def read_current(self):
        return list(self.current)

    def set_torque(self, enabled, hold=None):
        if enabled and hold is not None:
            # Goal first, torque second: a servo that gets torque with a stale
            # goal drives there at once, through whatever the fingers hold.
            self.write(hold)
        self.bus.sync_write(feetech.ADDR_TORQUE_ENABLE,
                            {i: [1 if enabled else 0] for i in self.active_ids})

    def close(self):
        try:
            self.bus.sync_write(feetech.ADDR_TORQUE_ENABLE, {i: [0] for i in self.active_ids})
        finally:
            self.bus.close()
