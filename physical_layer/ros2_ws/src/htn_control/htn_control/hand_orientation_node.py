"""Which way the hand points: /hand/orientation from the IMU of the wrist camera.

    /camera/imu            sensor_msgs/Imu, gyro + accelerometer united by the RealSense driver
    /hand/orientation      geometry_msgs/QuaternionStamped: base_link in a world with z up whose
                           yaw 0 is where the hand pointed at the start (no magnetometer: the
                           yaw is relative and drifts slowly, see orientation.py)
    /hand/reset_yaw        std_srvs/Trigger: where the hand points now becomes yaw 0

The IMU sits in the camera: its samples are turned into base_link with the camera's mount
angles (hand_params.yaml `camera.rpy`), so a change of that file needs no change here.
"""
import numpy as np
import rclpy
from geometry_msgs.msg import QuaternionStamped
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Imu
from std_srvs.srv import Trigger

from htn_control.hand_config import load_hand_params
from htn_control.orientation import OrientationFilter, from_rpy, quaternion

# The driver's IMU frame is optical (x right, y down, z forward); camera_link is x forward, y left, z up
LINK_FROM_OPTICAL = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])
MAX_DT = 0.1  # a gap longer than this is not integrated: the hand may have done anything in it


class HandOrientation(Node):

    def __init__(self):
        super().__init__('hand_orientation')
        params = load_hand_params(self.declare_parameter('params_file', '').value)
        rate = self.declare_parameter('rate', 30.0).value
        self.base_from_imu = from_rpy(*params['camera']['rpy']) @ LINK_FROM_OPTICAL
        self.filter = OrientationFilter()
        self.last_stamp = None
        self.publisher = self.create_publisher(QuaternionStamped, '/hand/orientation', 10)
        self.create_subscription(Imu, '/camera/imu', self.on_imu, qos_profile_sensor_data)
        self.create_service(Trigger, '/hand/reset_yaw', self.on_reset)
        self.create_timer(1.0 / rate, self.publish)
        self.silence_check = self.create_timer(8.0, self.on_silence)

    def on_silence(self):
        self.silence_check.cancel()  # once
        if self.filter.r is None:
            self.get_logger().warning(
                'No samples on /camera/imu: no /hand/orientation, the 3D hand will not turn. A RealSense D435 '
                '(USB id 8086:0b07) has no IMU - it takes a D435i (8086:0b3a). Check with `lsusb`.')

    def on_imu(self, message):
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        dt = 0.0 if self.last_stamp is None else stamp - self.last_stamp
        self.last_stamp = stamp
        if not 0.0 <= dt <= MAX_DT:
            return
        gyro, accel = message.angular_velocity, message.linear_acceleration
        first = self.filter.r is None
        self.filter.update(self.base_from_imu @ [gyro.x, gyro.y, gyro.z],
                           self.base_from_imu @ [accel.x, accel.y, accel.z], dt)
        if first and self.filter.r is not None:
            self.get_logger().info('IMU samples arrive: /hand/orientation is up, yaw 0 = where the hand points now')

    def on_reset(self, request, response):
        self.filter.reset_yaw()
        response.success, response.message = True, 'yaw 0 = where the hand points now'
        return response

    def publish(self):
        if self.filter.r is None:
            return  # no IMU (a D435 has none, or the camera is off): publish nothing rather than a guess
        message = QuaternionStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'base_link'
        q = message.quaternion
        q.x, q.y, q.z, q.w = quaternion(self.filter.r)
        self.publisher.publish(message)


def main():
    rclpy.init()
    node = HandOrientation()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
