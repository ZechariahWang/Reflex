"""RealSense -> rosbridge, for a machine that has the camera but no ROS (a Windows laptop next to
the Docker sim). Publishes the camera topics of the root CLAUDE.md contract through the rosbridge
websocket, in the same encodings the realsense2_camera driver uses, so the web console and the
policy adapter cannot tell the difference:

    /camera/color/image_raw/compressed                        JPEG
    /camera/color/camera_info
    /camera/aligned_depth_to_color/image_raw/compressedDepth  12-byte header + 16-bit PNG, millimetres
    /camera/aligned_depth_to_color/camera_info

    pip install -r requirements.txt
    python realsense_bridge.py --host localhost --port 9090

Not a ROS node: nothing here needs rclpy. Defaults match camera.launch.py (640x480 colour and
480x270 depth at 15 fps, what a USB 2 link sustains); `--depth 640x480x15` on USB 3.
"""

from __future__ import annotations

import argparse
import base64
import struct
import sys
import time

import cv2
import numpy as np
import pyrealsense2 as rs
import roslibpy

COLOR_TOPIC = "/camera/color/image_raw/compressed"
COLOR_INFO_TOPIC = "/camera/color/camera_info"
DEPTH_TOPIC = "/camera/aligned_depth_to_color/image_raw/compressedDepth"
DEPTH_INFO_TOPIC = "/camera/aligned_depth_to_color/camera_info"
COMPRESSED_IMAGE = "sensor_msgs/CompressedImage"
CAMERA_INFO = "sensor_msgs/CameraInfo"
OPTICAL_FRAME = "camera_color_optical_frame"
# compressed_depth_image_transport's ConfigHeader: int32 format, float32 depthParam[2]; all zero for 16UC1
DEPTH_HEADER = struct.pack("<iff", 0, 0.0, 0.0)
STATS_EVERY_S = 5.0


def profile(text: str) -> tuple[int, int, int]:
    width, height, fps = (int(v) for v in text.lower().split("x"))
    return width, height, fps


def stamp() -> dict:
    now = time.time()
    return {"sec": int(now), "nanosec": int((now % 1) * 1e9)}


def camera_info(intrinsics: rs.intrinsics) -> dict:
    fx, fy, cx, cy = intrinsics.fx, intrinsics.fy, intrinsics.ppx, intrinsics.ppy
    return {
        "header": {"stamp": stamp(), "frame_id": OPTICAL_FRAME},
        "width": intrinsics.width,
        "height": intrinsics.height,
        "distortion_model": "plumb_bob",
        "d": list(intrinsics.coeffs),
        "k": [fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0],
        "r": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        "p": [fx, 0.0, cx, 0.0, 0.0, fy, cy, 0.0, 0.0, 0.0, 1.0, 0.0],
        "binning_x": 0,
        "binning_y": 0,
        "roi": {"x_offset": 0, "y_offset": 0, "height": 0, "width": 0, "do_rectify": False},
    }


def start_pipeline(color: tuple[int, int, int], depth: tuple[int, int, int]) -> rs.pipeline:
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, color[0], color[1], rs.format.bgr8, color[2])
    config.enable_stream(rs.stream.depth, depth[0], depth[1], rs.format.z16, depth[2])
    pipeline.start(config)
    return pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="localhost", help="machine running rosbridge")
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--color", default="640x480x15", help="colour profile WxHxFPS")
    parser.add_argument("--depth", default="480x270x15", help="depth profile WxHxFPS (aligned to the colour size)")
    parser.add_argument("--jpeg-quality", type=int, default=80)
    args = parser.parse_args()

    ros = roslibpy.Ros(args.host, args.port)
    ros.run(timeout=10)
    if not ros.is_connected:
        print(f"no rosbridge at ws://{args.host}:{args.port}", file=sys.stderr)
        return 1
    topics = {
        name: roslibpy.Topic(ros, name, kind, queue_size=1)
        for name, kind in (
            (COLOR_TOPIC, COMPRESSED_IMAGE),
            (COLOR_INFO_TOPIC, CAMERA_INFO),
            (DEPTH_TOPIC, COMPRESSED_IMAGE),
            (DEPTH_INFO_TOPIC, CAMERA_INFO),
        )
    }
    for topic in topics.values():
        topic.advertise()

    color, depth = profile(args.color), profile(args.depth)
    try:
        pipeline = start_pipeline(color, depth)
    except RuntimeError as error:
        print(f"{error}; retrying with the depth at the colour size", file=sys.stderr)
        pipeline = start_pipeline(color, color)
    active = pipeline.get_active_profile()
    device = active.get_device()
    depth_scale = device.first_depth_sensor().get_depth_scale()  # metres per unit, 0.001 on a D435
    to_mm = depth_scale * 1000.0
    intrinsics = active.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
    align = rs.align(rs.stream.color)
    print(
        f"{device.get_info(rs.camera_info.name)} on {device.get_info(rs.camera_info.usb_type_descriptor)}: "
        f"colour {args.color}, depth {args.depth} aligned to {intrinsics.width}x{intrinsics.height}, "
        f"fx {intrinsics.fx:.1f} -> ws://{args.host}:{args.port}",
        flush=True,
    )

    frames_sent = 0
    bytes_sent = 0
    last_stats = time.monotonic()
    try:
        while ros.is_connected:
            frames = align.process(pipeline.wait_for_frames())
            color_frame, depth_frame = frames.get_color_frame(), frames.get_depth_frame()
            if not color_frame or not depth_frame:
                continue
            bgr = np.asanyarray(color_frame.get_data())
            depth_units = np.asanyarray(depth_frame.get_data())
            depth_mm = depth_units if to_mm == 1.0 else np.clip(depth_units * to_mm, 0, 65535).astype(np.uint16)

            ok_jpeg, jpeg = cv2.imencode(".jpg", bgr, (cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality))
            ok_png, png = cv2.imencode(".png", depth_mm, (cv2.IMWRITE_PNG_COMPRESSION, 1))
            if not (ok_jpeg and ok_png):
                continue
            header = {"stamp": stamp(), "frame_id": OPTICAL_FRAME}
            info = camera_info(intrinsics)
            topics[COLOR_TOPIC].publish(
                roslibpy.Message({"header": header, "format": "jpeg", "data": base64.b64encode(jpeg.tobytes()).decode()})
            )
            topics[DEPTH_TOPIC].publish(
                roslibpy.Message(
                    {
                        "header": header,
                        "format": "16UC1; compressedDepth png",
                        "data": base64.b64encode(DEPTH_HEADER + png.tobytes()).decode(),
                    }
                )
            )
            topics[COLOR_INFO_TOPIC].publish(roslibpy.Message(info))
            topics[DEPTH_INFO_TOPIC].publish(roslibpy.Message(info))

            frames_sent += 1
            bytes_sent += len(jpeg) + len(png)
            now = time.monotonic()
            if now - last_stats >= STATS_EVERY_S:
                elapsed = now - last_stats
                print(f"{frames_sent / elapsed:.1f} fps, {bytes_sent / elapsed / 1e6:.2f} MB/s", flush=True)
                frames_sent, bytes_sent, last_stats = 0, 0, now
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.stop()
        for topic in topics.values():
            topic.unadvertise()
        ros.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
