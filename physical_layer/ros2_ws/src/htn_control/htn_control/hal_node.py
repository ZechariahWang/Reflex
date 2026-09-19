import math

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool, Float64MultiArray
from std_srvs.srv import SetBool

from htn_control.hal import BACKENDS
from htn_control.hal.contact import BLOCKED, ContactDetector
from htn_control.hand_config import FINGERS, load_hand_params

COMMAND_TOPIC = '/hand/command'  # Float64MultiArray, 5 x [0..1], FINGERS order
STATE_TOPIC = '/hand/state'      # same layout, measured (or commanded if unknown)
PASSIVE_TOPIC = '/hand/passive'  # Bool, latched: True while the fingers are backdriven
PASSIVE_SERVICE = '/hand/set_passive'  # std_srvs/SetBool


class HandHal(Node):
    """Hardware abstraction layer for the hand.

    Teleop and the autonomous node only ever publish normalized finger
    positions on /hand/command; this node clamps and rate-limits them and
    hands them to whichever backend is selected (sim | feetech).

    Passive (backdrive) mode is for recording demonstrations: the torque is
    off, a person moves the fingers, and /hand/state keeps reporting the
    encoders. Commands are ignored meanwhile. Leaving the mode holds the pose
    the fingers are in, so the hand never snaps back to an old target.

    Nothing is driven blind. The motors get torque only once the first measured
    pose is in, with that pose as their goal; a finger that starts outside its
    calibrated travel is swept into it at the normal speed, it does not jump to
    the edge. On backends with a torque limit a finger that has to move and does
    not is put on a low holding torque (hal/contact.py).
    """

    def __init__(self):
        super().__init__('hand_hal')
        backend_name = self.declare_parameter('backend', 'sim').value
        params_file = self.declare_parameter('params_file', '').value
        rate = self.declare_parameter('rate', 50.0).value
        # Fastest a finger may travel, in full ranges per second
        self.max_speed = self.declare_parameter('max_speed', 2.0).value
        # How hard a finger may speed up and brake, in full ranges per second^2. A move is one
        # sweep: ease in, cruise at max_speed, brake to arrive with zero speed. Without it the
        # setpoint starts and stops dead, which a servo answers with a lurch and a crawl.
        self.max_accel = self.declare_parameter('max_accel', 20.0).value
        # Start with the torque off (a data collection session)
        start_passive = self.declare_parameter('passive', False).value

        self.hand_params = load_hand_params(params_file)
        if backend_name not in BACKENDS:
            raise ValueError(f"backend must be one of {list(BACKENDS)}, got '{backend_name}'")
        self.backend = BACKENDS[backend_name](self, self.hand_params)

        self.dt = 1.0 / rate
        self.target = [0.0] * len(FINGERS)
        self.setpoint = [0.0] * len(FINGERS)
        self.velocity = [0.0] * len(FINGERS)
        self.ready = False      # True once the first measured pose has been adopted
        self.commanded = False  # a command that arrives before that must survive it
        stop = self.hand_params.get('contact_stop', {})
        self.contacts = []
        if self.backend.has_torque_limit and stop.get('enabled', True):
            self.contacts = [ContactDetector(stop.get('blocked_error', 0.06), stop.get('blocked_motion', 0.004),
                                             stop.get('blocked_cycles', 10), stop.get('hold_lead', 0.03),
                                             stop.get('blocked_current'), stop.get('blocked_excess', 150))
                             for _ in FINGERS]

        self.create_subscription(Float64MultiArray, COMMAND_TOPIC, self.on_command, 10)
        self.command_pub = self.create_publisher(Float64MultiArray, COMMAND_TOPIC, 10)
        self.state_pub = self.create_publisher(Float64MultiArray, STATE_TOPIC, 10)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.passive_pub = self.create_publisher(Bool, PASSIVE_TOPIC, latched)
        self.create_service(SetBool, PASSIVE_SERVICE, self.on_set_passive)
        self.passive = False
        self.passive_pub.publish(Bool(data=False))
        if start_passive:
            self.set_passive(True)
        self.joint_state_pub = None
        if not self.backend.publishes_joint_states:
            self.joint_state_pub = self.create_publisher(JointState, '/joint_states', 10)
        self.create_timer(self.dt, self.update)
        self.get_logger().info(f"Hand HAL up, backend '{backend_name}'")

    def set_passive(self, passive):
        if passive == self.passive:
            return
        if passive:
            self.backend.set_torque(False)
        else:
            # update() kept the setpoint on the measured pose while passive
            self.velocity = [0.0] * len(FINGERS)
            self.release_contacts()
            if self.ready:
                self.backend.set_torque(True, hold=self.setpoint)
            # One message so every controller on the shared topic (control
            # window, web console) starts from the real pose, not a stale one
            self.command_pub.publish(Float64MultiArray(data=self.target))  # the pose, within 0..1
        self.passive = passive
        self.passive_pub.publish(Bool(data=passive))
        self.get_logger().info(
            'Passive: torque off, move the fingers by hand' if passive
            else f'Active: torque on, holding {[round(p, 2) for p in self.setpoint]}')

    def on_set_passive(self, request, response):
        self.set_passive(request.data)
        response.success = True
        response.message = 'passive' if self.passive else 'active'
        return response

    def on_command(self, msg):
        if self.passive:
            self.get_logger().warning(
                'Ignoring /hand/command: the hand is passive (torque off)',
                throttle_duration_sec=5.0)
            return
        if len(msg.data) != len(FINGERS):
            self.get_logger().warning(
                f'Ignoring command with {len(msg.data)} values, expected {len(FINGERS)}',
                throttle_duration_sec=2.0)
            return
        self.target = [min(max(v, 0.0), 1.0) for v in msg.data]
        self.commanded = True

    def adopt(self, state):
        """Make the measured pose the setpoint. NOT clamped: a finger outside its calibrated
        travel is held where it is and then swept into range, it must not jump to the edge."""
        self.setpoint = list(state)
        self.velocity = [0.0] * len(FINGERS)
        if self.passive or not self.commanded:
            self.target = [min(max(p, 0.0), 1.0) for p in state]

    def release_contacts(self):
        for finger, contact in enumerate(self.contacts):
            if contact.state == BLOCKED:
                self.backend.set_torque_limit(finger, False)
            contact.reset()

    def update(self):
        if not self.ready:
            state = self.backend.read()
            if state is None:
                return  # no measured pose yet (sim: no joint states so far): command nothing
            self.adopt(state)
            if not self.passive:
                self.backend.set_torque(True, hold=self.setpoint)
            self.ready = True

        if self.passive:
            state = self.backend.read()
            if state is not None:
                self.adopt(state)  # follow the fingers, so leaving passive mode holds this pose
            self.publish_state(state or self.setpoint)
            return

        for i, target in enumerate(self.target):
            if self.contacts and self.contacts[i].state == BLOCKED:
                self.setpoint[i], self.velocity[i] = self.contacts[i].hold_setpoint(), 0.0
            else:
                self.setpoint[i], self.velocity[i] = self.sweep(self.setpoint[i], self.velocity[i], target)
        self.backend.write(self.setpoint)
        state = self.backend.read()
        if state is not None:
            currents = self.backend.read_current() or [None] * len(FINGERS)
            for i, contact in enumerate(self.contacts):
                before = contact.state
                after = contact.update(self.setpoint[i], state[i], self.target[i], currents[i])
                if after == before:
                    continue
                self.backend.set_torque_limit(i, after == BLOCKED)
                if after == BLOCKED:
                    self.get_logger().info(f'{FINGERS[i]}: blocked at {state[i]:.2f} (setpoint {self.setpoint[i]:.2f}, '
                                           f'{currents[i] or 0:.0f} mA), holding with low torque')
                else:
                    self.get_logger().info(f'{FINGERS[i]}: free again')
                    # pick the sweep up from where the finger is, not from the frozen setpoint
                    self.setpoint[i], self.velocity[i] = state[i], 0.0
        self.publish_state(state or self.setpoint)

    def sweep(self, position, velocity, target):
        """One tick of a speed- and acceleration-limited move towards `target`."""
        distance = target - position
        step_limit = self.max_accel * self.dt  # largest change of speed in one tick
        # Fastest speed from which we can still brake to rest AT the target, counting the ground
        # covered during this tick: v * dt + v^2 / 2a <= |distance|. The continuous-time
        # sqrt(2 a d) ignores the first term and runs a few percent past the target.
        brake = -step_limit + math.sqrt(step_limit * step_limit + 2.0 * self.max_accel * abs(distance))
        wanted = math.copysign(min(self.max_speed, brake), distance)
        velocity += min(max(wanted - velocity, -step_limit), step_limit)
        step = velocity * self.dt
        if abs(distance) <= abs(step) or (abs(distance) < 1e-4 and abs(velocity) <= step_limit):
            return target, 0.0  # within this tick's reach: land exactly, at rest
        return position + step, velocity

    def publish_state(self, state):
        self.state_pub.publish(Float64MultiArray(data=state))
        if self.joint_state_pub is not None:
            self.publish_joint_states(state)

    def publish_joint_states(self, state):
        fingers = self.hand_params['fingers']
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = [f + '_joint' for f in FINGERS]
        msg.position = [
            fingers[f]['min_angle'] + p * (fingers[f]['max_angle'] - fingers[f]['min_angle'])
            for f, p in zip(FINGERS, state)]
        self.joint_state_pub.publish(msg)


def main():
    rclpy.init()
    node = HandHal()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.backend.close()
        node.destroy_node()
        rclpy.try_shutdown()
