"""Head camera: the forehead iPhone (Record3D app, USB) as a ROS camera.

    /head_camera/color/image_raw/compressed   sensor_msgs/CompressedImage, jpeg
    /head_camera/color/camera_info
    /head_camera/aligned_depth_to_color/image_raw/compressedDepth   16UC1 millimetres, the LiDAR,
        turned and sized as the colour picture (so camera_info is the same one). Not for the
        policy: for the console's object map when the phone is the only camera.

Design: docs/specs/iphone-camera-design.md. The record3d library runs in a child
process (iphone_worker.py says why); this node turns, shrinks, encodes and
publishes each frame, and starts a new worker when one ends. The rotation and the
size are part of a recorded dataset: do not change them after the first recording.
"""
import multiprocessing
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, CompressedImage

from htn_control import iphone_worker

FRAME_ID = 'head_camera_color_optical_frame'  # no TF: the head is not attached to the hand
ROTATIONS = {0: None, 90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
RETRY_MIN_S, RETRY_MAX_S = 1.0, 8.0
START_TIMEOUT_S = 12.0       # spawn an interpreter, ask usbmuxd for devices, connect
# A connection that stays silent is dead on the phone's side (the app streams to its newest
# client and never closes the old one). Reconnecting is safe - killing the worker really
# closes the socket - and the app resumes at once, so do not sit on a silent one.
FIRST_FRAME_TIMEOUT_S = 5.0
FRAME_TIMEOUT_S = 3.0


def prepare(rgb, rotation, width, height):
    """The sensor's picture -> the published one: turned clockwise by `rotation`, then width x height."""
    turn = ROTATIONS[rotation]
    turned = rgb if turn is None else cv2.rotate(rgb, turn)
    return cv2.resize(turned, (width, height), interpolation=cv2.INTER_AREA)


def prepare_depth(depth_m, rotation, width, height):
    """The LiDAR's metres -> uint16 millimetres on the pixels of prepare()'s picture. 0 = no reading.
    Nearest neighbour: a hole stays a hole and is not smeared into the depths next to it."""
    mm = np.nan_to_num(depth_m * 1000.0, nan=0.0, posinf=0.0, neginf=0.0)
    mm = np.clip(mm, 0.0, 65535.0).round().astype(np.uint16)
    turn = ROTATIONS[rotation]
    turned = mm if turn is None else cv2.rotate(mm, turn)
    return cv2.resize(turned, (width, height), interpolation=cv2.INTER_NEAREST)


def compressed_depth(mm):
    """The data of a `16UC1; compressedDepth png` message, as compressed_depth_image_transport makes
    it: its 12-byte header (format, two depth parameters: unused for 16UC1) and then the PNG."""
    ok, png = cv2.imencode('.png', mm, (cv2.IMWRITE_PNG_COMPRESSION, 1))
    return bytes(12) + png.tobytes() if ok else None


def camera_matrix(k, shape, rotation, width, height):
    """(fx, fy, cx, cy) of the sensor's picture (`shape` = its rows, columns) -> the same of the
    picture that prepare() makes of it. Pixel centres are whole numbers."""
    fx, fy, cx, cy = k
    rows, columns = shape[:2]
    if rotation == 90:
        fx, fy, cx, cy, rows, columns = fy, fx, rows - 1 - cy, cx, columns, rows
    elif rotation == 180:
        cx, cy = columns - 1 - cx, rows - 1 - cy
    elif rotation == 270:
        fx, fy, cx, cy, rows, columns = fy, fx, cy, columns - 1 - cx, columns, rows
    sx, sy = width / columns, height / rows
    return fx * sx, fy * sy, (cx + 0.5) * sx - 0.5, (cy + 0.5) * sy - 0.5


def supervise(session, log, stopped, sleep=time.sleep):
    """Run `session()` again and again until `stopped()`. A session returns (why it ended, whether
    it had streamed). Backoff 1 .. 8 s; the reason is logged once per change, not once per try."""
    delay, last = RETRY_MIN_S, None
    while not stopped():
        reason, streamed = session()
        if streamed:
            delay, last = RETRY_MIN_S, None  # it worked a moment ago: retry promptly, and say why it ended
        if reason != last and not stopped():
            log(reason)
            last = reason
        sleep(delay)
        delay = min(delay * 2, RETRY_MAX_S)


class IphoneCamera(Node):
    make_stream = staticmethod(iphone_worker.record3d_stream)  # the tests put a fake phone here

    def __init__(self):
        super().__init__('iphone_camera')
        self.rotation = self.declare_parameter('rotation', 270).value
        self.width = self.declare_parameter('width', 640).value
        self.height = self.declare_parameter('height', 480).value
        self.max_fps = self.declare_parameter('max_fps', 15.0).value
        self.jpeg_quality = self.declare_parameter('jpeg_quality', 80).value
        self.depth = self.declare_parameter('depth', True).value
        if self.rotation not in ROTATIONS:
            raise ValueError(f'rotation must be one of {sorted(ROTATIONS)}, got {self.rotation}')
        self.image_pub = self.create_publisher(CompressedImage, '/head_camera/color/image_raw/compressed', 1)
        self.info_pub = self.create_publisher(CameraInfo, '/head_camera/color/camera_info', 1)
        self.depth_pub = self.create_publisher(
            CompressedImage, '/head_camera/aligned_depth_to_color/image_raw/compressedDepth', 1)
        self.closing = threading.Event()
        self.thread = threading.Thread(target=supervise, daemon=True, args=(
            self.session, lambda reason: self.get_logger().warning(f'{reason}. Trying again by itself.'),
            self.closing.is_set, self.closing.wait))
        self.thread.start()

    def session(self):
        """One worker from start to end. Returns (why it ended, whether it had streamed)."""
        context = multiprocessing.get_context('spawn')  # never fork a process that has ROS threads
        receiver, sender = context.Pipe(duplex=False)
        worker = context.Process(target=iphone_worker.run, args=(sender, self.max_fps, self.make_stream, self.depth),
                                 name='record3d-usb', daemon=True)
        worker.start()
        sender.close()
        # Frames can overtake the "connected" notice (the library starts reading before
        # connect() returns), so every message is handled in whatever order it arrives.
        timeout, problem, streamed = START_TIMEOUT_S, iphone_worker.USB_STUCK, False
        try:
            while not self.closing.is_set():
                if not receiver.poll(timeout):
                    return problem, streamed
                message = receiver.recv()
                if message[0] == 'frame':
                    if not streamed:
                        self.get_logger().info(f'iPhone streaming, {message[1].shape[1]} x {message[1].shape[0]}')
                    timeout, problem, streamed = FRAME_TIMEOUT_S, iphone_worker.USB_SILENT, True
                    self.publish(*message[1:])
                elif message[0] == 'connected' and not streamed:
                    timeout, problem = FIRST_FRAME_TIMEOUT_S, iphone_worker.USB_SILENT
                elif message[0] == 'error':
                    return message[1], streamed
                elif message[0] == 'stopped':
                    return iphone_worker.STOPPED, streamed
            return 'shutting down', streamed
        except (EOFError, OSError):
            return 'the worker process died', streamed
        finally:
            worker.kill()  # the one disconnect that really closes the socket to the phone
            worker.join(3.0)
            receiver.close()

    def publish(self, rgb, k, depth_m=None):
        picture = prepare(rgb, self.rotation, self.width, self.height)
        ok, jpeg = cv2.imencode('.jpg', cv2.cvtColor(picture, cv2.COLOR_RGB2BGR),
                                (cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality))
        if not ok:
            return
        image = CompressedImage(format='jpeg', data=jpeg.tobytes())
        image.header.stamp = self.get_clock().now().to_msg()  # the time the frame arrived
        image.header.frame_id = FRAME_ID
        fx, fy, cx, cy = camera_matrix(k, rgb.shape, self.rotation, self.width, self.height)
        info = CameraInfo(header=image.header, width=self.width, height=self.height,
                          distortion_model='plumb_bob', d=[0.0] * 5,
                          k=[fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0],
                          r=np.eye(3).flatten().tolist(),
                          p=[fx, 0.0, cx, 0.0, 0.0, fy, cy, 0.0, 0.0, 0.0, 1.0, 0.0])
        self.image_pub.publish(image)
        self.info_pub.publish(info)
        if depth_m is not None:
            data = compressed_depth(prepare_depth(depth_m, self.rotation, self.width, self.height))
            if data is not None:
                self.depth_pub.publish(CompressedImage(header=image.header, format='16UC1; compressedDepth png',
                                                       data=data))

    def close(self):
        self.closing.set()
        self.thread.join(5.0)  # the session kills its worker on the way out


def main():
    rclpy.init()
    node = IphoneCamera()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.close()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
