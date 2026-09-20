"""Play a recorded episode back through rosbridge: the hand does what it was told, the console shows what the cameras saw.

    python -m lerobot_robot_exo_hand.replay --root policy/datasets/exo_grasp --episode 0 --host <ros-ip>

Each frame of the episode, at the fps it was recorded with:
  action                      -> /hand/command  (the sim's or the real hand moves; `--what state`
                                 sends the measured observation.state instead: what the hand DID)
  observation.images.camera1  -> /head_camera/color/image_raw/compressed
  observation.images.camera2  -> /camera/color/image_raw/compressed

The images are for a ROS side with NO camera running (sim.launch.py camera:=none): the web console
and Foxglove then show the recording in their camera panels. With a live camera on those topics
pass --no-images, or the two pictures flicker over each other. It commands the hand: on the real
one, clear its surroundings first, as for any command.
"""

import argparse
import base64
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

import cv2
import numpy as np

from .convert import CAMERA, HEAD_CAMERA

COMMAND_TOPIC = "/hand/command"
IMAGE_TOPICS = {HEAD_CAMERA: "/head_camera/color/image_raw/compressed", CAMERA: "/camera/color/image_raw/compressed"}
FRAME_IDS = {HEAD_CAMERA: "head_camera_color_optical_frame", CAMERA: "camera_color_optical_frame"}
JPEG_QUALITY = 80

# One frame of an episode: the five finger values to send, and a JPEG for each camera it has
Frame = tuple[list[float], dict[str, bytes]]


def to_jpeg(image) -> bytes:
    """A dataset image (channels first, RGB, float 0..1 or uint8; a tensor or an array) -> JPEG bytes."""
    array = np.asarray(image)
    if array.ndim == 3 and array.shape[0] in (1, 3) and array.shape[-1] not in (1, 3):
        array = np.moveaxis(array, 0, -1)
    if array.dtype != np.uint8:
        array = (np.clip(array, 0.0, 1.0) * 255.0).round().astype(np.uint8)
    ok, jpeg = cv2.imencode(".jpg", cv2.cvtColor(array, cv2.COLOR_RGB2BGR), (cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY))
    if not ok:
        raise ValueError("JPEG encode failed")
    return jpeg.tobytes()


def episode_frames(root: Path, episode: int, what: str = "action", images: bool = True) -> tuple[float, Iterator[Frame]]:
    """(fps, frames) of one episode of the LeRobot dataset at root. The frames are made one by one
    (each decodes video); `play` wants them as a list, so that a slow decode is not part of the timing."""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    root = Path(root)
    dataset = LeRobotDataset(root.name, root=root, episodes=[episode])
    column = "action" if what == "action" else "observation.state"

    def frames() -> Iterator[Frame]:
        for index in range(len(dataset)):
            item = dataset[index]
            pictures = {
                key: to_jpeg(item[f"observation.images.{key}"])
                for key in IMAGE_TOPICS
                if images and f"observation.images.{key}" in item
            }
            yield [float(v) for v in item[column]], pictures

    return float(dataset.fps), frames()


def play(
    frames: Iterable[Frame],
    fps: float,
    send_command: Callable[[list[float]], None],
    send_image: Callable[[str, bytes], None],
    speed: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Send every frame at its time: frame i at start + i / (fps * speed), however long a send took.
    A frame that is already late goes out at once - the replay never runs ahead and never queues."""
    if fps <= 0 or speed <= 0:
        raise ValueError(f"fps and speed must be positive: fps={fps}, speed={speed}")
    start = clock()
    count = 0
    for count, (values, pictures) in enumerate(frames, start=1):
        sleep(max(0.0, start + (count - 1) / (fps * speed) - clock()))
        send_command(values)
        for key, jpeg in pictures.items():
            send_image(key, jpeg)
    return count


def main() -> None:
    import roslibpy

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, help="folder of the dataset, e.g. policy/datasets/exo_grasp")
    parser.add_argument("--episode", type=int, default=0)
    parser.add_argument("--host", default="localhost", help="the ROS machine (rosbridge)")
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--what", choices=["action", "state"], default="action",
                        help="action = what the hand was told (the training label), state = what it measured")
    parser.add_argument("--speed", type=float, default=1.0, help="0.5 = half speed")
    parser.add_argument("--no-images", action="store_true", help="only move the hand: a live camera owns the image topics")
    parser.add_argument("--loop", action="store_true", help="again and again until Ctrl-C")
    args = parser.parse_args()

    fps, frames = episode_frames(args.root, args.episode, args.what, images=not args.no_images)
    print(f"loading episode {args.episode} of {args.root} ...")
    frames = list(frames)
    print(f"{len(frames)} frames at {fps:g} fps = {len(frames) / fps:.1f} s, cameras: {sorted(frames[0][1]) if frames else []}")

    ros = roslibpy.Ros(args.host, args.port)
    ros.run(timeout=10)
    command = roslibpy.Topic(ros, COMMAND_TOPIC, "std_msgs/Float64MultiArray", queue_size=1)
    pictures = {key: roslibpy.Topic(ros, topic, "sensor_msgs/CompressedImage", queue_size=1) for key, topic in IMAGE_TOPICS.items()}
    for topic in [command, *pictures.values()]:
        topic.advertise()
    time.sleep(0.5)  # rosbridge needs a moment between advertise and the first message

    def send_image(key: str, jpeg: bytes) -> None:
        now = time.time()
        pictures[key].publish({
            "header": {"stamp": {"sec": int(now), "nanosec": int(now % 1 * 1e9)}, "frame_id": FRAME_IDS[key]},
            "format": "jpeg",
            "data": base64.b64encode(jpeg).decode(),
        })

    try:
        while True:
            sent = play(frames, fps, lambda values: command.publish({"data": values}), send_image, args.speed)
            print(f"sent {sent} frames")
            if not args.loop:
                break
    except KeyboardInterrupt:
        pass
    finally:
        ros.terminate()


if __name__ == "__main__":
    main()
