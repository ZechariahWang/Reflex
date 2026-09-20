"""Head camera: the pure parts, the worker on a fake phone, the reconnect, then the node end to end."""
import multiprocessing
import os
import threading

import cv2
import numpy as np
import pytest

from fake_phone import COLUMNS, ROWS, NoPhone, Refuses, FakeStream, Streams, portrait_frame
from htn_control import iphone_worker
from htn_control.iphone_camera_node import camera_matrix, compressed_depth, prepare, prepare_depth, supervise

# Where the red top left corner of the portrait frame is after the turn (row, column of 480 x 640)
CORNER = {0: (20, 20), 90: (20, 620), 180: (460, 620), 270: (460, 20)}


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_prepare_turns_clockwise_and_always_gives_480_by_640(rotation):
    picture = prepare(portrait_frame(), rotation, 640, 480)
    assert picture.shape == (480, 640, 3)
    red = {corner: tuple(picture[corner]) == (255, 0, 0) for corner in CORNER.values()}
    assert red == {corner: corner == CORNER[rotation] for corner in CORNER.values()}


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_the_principal_point_follows_the_picture(rotation):
    # a principal point in the middle of the red corner must land in the red corner
    fx, fy, cx, cy = camera_matrix((700.0, 710.0, 50.0, 50.0), (ROWS, COLUMNS), rotation, 640, 480)
    picture = prepare(portrait_frame(), rotation, 640, 480)
    assert tuple(picture[round(cy), round(cx)]) == (255, 0, 0)
    turned = rotation in (90, 270)  # fx / fy swap; then the shrink of that axis
    assert fx == pytest.approx((710.0 if turned else 700.0) * 640 / (ROWS if turned else COLUMNS))
    assert fy == pytest.approx((700.0 if turned else 710.0) * 480 / (COLUMNS if turned else ROWS))


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_the_depth_lands_on_the_pixels_of_the_picture_in_millimetres(rotation):
    mm = prepare_depth(FakeStream().get_depth_frame(), rotation, 640, 480)
    assert mm.shape == (480, 640) and mm.dtype == np.uint16
    near = {corner: int(mm[corner]) for corner in CORNER.values()}
    assert near == {corner: 500 if corner == CORNER[rotation] else 1500 for corner in CORNER.values()}
    payload = compressed_depth(mm)  # what the backend's depth.decode() does with it
    assert np.array_equal(cv2.imdecode(np.frombuffer(payload, np.uint8, offset=12), cv2.IMREAD_UNCHANGED), mm)


def test_the_middle_stays_the_middle():
    k = (700.0, 700.0, (COLUMNS - 1) / 2, (ROWS - 1) / 2)
    for rotation in (0, 90, 180, 270):
        assert camera_matrix(k, (ROWS, COLUMNS), rotation, 640, 480)[2:] == pytest.approx((319.5, 239.5))


def test_the_rate_cap_takes_15_of_60_fps():
    now = [0.0]
    cap = iphone_worker.RateCap(15.0, clock=lambda: now[0])
    accepted = []
    for frame in range(600):  # 10 s at 60 fps
        now[0] = frame / 60
        if cap.accept():
            accepted.append(now[0])
    assert 140 <= len(accepted) <= 160
    assert min(b - a for a, b in zip(accepted, accepted[1:])) >= 0.9 / 15 - 1e-9


def worker_messages(stream_class, count):
    receiver, sender = multiprocessing.Pipe(duplex=False)
    threading.Thread(target=iphone_worker.run, args=(sender, 15.0, stream_class), daemon=True).start()
    return [receiver.recv() for _ in range(count) if receiver.poll(5.0)]


def test_the_worker_says_what_to_do_when_there_is_no_phone_or_the_app_refuses():
    assert worker_messages(NoPhone, 1) == [('error', iphone_worker.NO_PHONE)]
    assert worker_messages(Refuses, 1) == [('error', iphone_worker.NOT_ACCEPTING)]


def test_the_worker_sends_the_frame_with_its_intrinsics():
    frame, connected = worker_messages(FakeStream, 2)
    assert connected == ('connected',)
    assert frame[0] == 'frame' and frame[2] == (700.0, 710.0, 359.5, 479.5)
    assert frame[3].dtype == np.float32 and frame[3].shape == (ROWS // 4, COLUMNS // 4)
    assert np.array_equal(frame[1], portrait_frame())


def test_a_session_that_ends_is_started_again_after_the_backoff_and_the_reason_is_logged_once():
    ends = [('no phone', False)] * 5 + [('stopped', True), ('no phone', False), ('no phone', False)]
    sessions, logged, slept = iter(ends), [], []
    supervise(lambda: next(sessions), logged.append, lambda: len(slept) == len(ends), slept.append)
    assert slept == [1.0, 2.0, 4.0, 8.0, 8.0, 1.0, 2.0, 4.0]  # it had streamed: prompt again
    assert logged == ['no phone', 'stopped', 'no phone']


def test_the_node_publishes_the_turned_jpeg_and_its_camera_info(monkeypatch):
    os.environ['ROS_DOMAIN_ID'] = '77'  # a private ROS graph, as the HAL tests
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    import rclpy
    from sensor_msgs.msg import CameraInfo, CompressedImage
    from htn_control.iphone_camera_node import FRAME_ID, IphoneCamera

    monkeypatch.setattr(IphoneCamera, 'make_stream', staticmethod(Streams))
    rclpy.init()
    node = IphoneCamera()
    images, infos, depths = [], [], []
    node.create_subscription(CompressedImage, '/head_camera/aligned_depth_to_color/image_raw/compressedDepth',
                             depths.append, 1)
    node.create_subscription(CompressedImage, '/head_camera/color/image_raw/compressed', images.append, 1)
    node.create_subscription(CameraInfo, '/head_camera/color/camera_info', infos.append, 1)
    try:
        for _ in range(200):
            rclpy.spin_once(node, timeout_sec=0.1)
            if len(images) >= 3 and infos and depths:
                break
        assert len(images) >= 3, 'no frames from the fake phone'
        picture = cv2.imdecode(np.frombuffer(bytes(images[0].data), np.uint8), cv2.IMREAD_COLOR)
        assert images[0].format == 'jpeg' and images[0].header.frame_id == FRAME_ID
        assert picture.shape == (480, 640, 3)
        assert picture[460, 20, 2] > 200 and picture[460, 20, 0] < 60, 'rotation 270: the red corner is bottom left (BGR)'
        assert (infos[0].width, infos[0].height) == (640, 480) and infos[0].header.frame_id == FRAME_ID
        assert infos[0].k[0] == pytest.approx(710.0 * 640 / ROWS)
        mm = cv2.imdecode(np.frombuffer(bytes(depths[0].data), np.uint8, offset=12), cv2.IMREAD_UNCHANGED)
        assert depths[0].format == '16UC1; compressedDepth png' and mm.shape == (480, 640)
        assert (mm[460, 20], mm[240, 320]) == (500, 1500), 'the near corner is where the red corner is'
    finally:
        node.close()
        node.destroy_node()
        rclpy.shutdown()
