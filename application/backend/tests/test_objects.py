import pytest
import numpy as np

from app.hub import Hub
from app.config import Settings
from app.objects import CONFIRM_HITS, Detection, Intrinsics, Located, MockObjects, Tracker, locate


def intrinsics() -> Intrinsics:
    return Intrinsics(fx=600.0, fy=600.0, cx=320.0, cy=240.0, width=640, height=480)


def flat_depth(mm: int) -> np.ndarray:
    return np.full((480, 640), mm, dtype=np.uint16)


def test_locate_projects_the_box_centre_into_camera_link():
    # A 60 x 120 px box centred 60 px right of and 30 px below the principal point, at 0.5 m
    box = Detection("cup", 0.9, (350.0, 210.0, 410.0, 330.0))
    placed = locate(box, flat_depth(500), intrinsics())
    assert placed is not None
    x, y, z = placed.xyz
    assert abs(x - 0.5) < 1e-6  # forward = depth
    assert abs(y - -0.05) < 1e-6  # right of centre in the image = -y (left is positive)
    assert abs(z - -0.025) < 1e-6  # below centre = -z
    depth_extent, width, height = placed.size
    assert abs(width - 0.05) < 1e-6 and abs(height - 0.1) < 1e-6 and depth_extent == min(width, height)


def test_locate_reads_the_middle_of_the_box_and_needs_enough_depth():
    depth = flat_depth(900)
    depth[200:280, 280:360] = 400  # the object; the rest of the box is background
    placed = locate(Detection("bottle", 0.8, (240.0, 160.0, 400.0, 320.0)), depth, intrinsics())
    assert placed is not None and abs(placed.xyz[0] - 0.4) < 1e-6
    assert locate(Detection("bottle", 0.8, (0.0, 0.0, 30.0, 30.0)), flat_depth(0), intrinsics()) is None


def test_locate_scales_the_box_when_depth_and_colour_differ():
    depth = np.zeros((270, 480), dtype=np.uint16)
    depth[100:170, 200:280] = 700
    # Same region in 640x480 colour pixels
    placed = locate(Detection("apple", 0.7, (266.0, 178.0, 373.0, 302.0)), depth, intrinsics())
    assert placed is not None and abs(placed.xyz[0] - 0.7) < 1e-6


def test_camera_info_uses_the_ros2_lowercase_matrix():
    message = {"k": [610.0, 0, 321.0, 0, 611.0, 239.0, 0, 0, 1], "width": 640, "height": 480}
    k = Intrinsics.from_camera_info(message)
    assert (k.fx, k.fy, k.cx, k.cy) == (610.0, 611.0, 321.0, 239.0)


def test_tracker_confirms_associates_smooths_and_forgets():
    tracker = Tracker(gate_m=0.2, memory_s=5.0)
    cup = Located("cup", 0.9, (0.5, 0.0, 0.0), (0.08, 0.08, 0.1))
    tracker.update([cup], now=0.0)
    assert tracker.objects(0.0) == []  # one sighting is not yet an object
    tracker.update([Located("cup", 0.9, (0.52, 0.0, 0.0), cup.size)], now=0.1)
    (only,) = tracker.objects(0.1)
    assert only["label"] == "cup" and only["hits"] == CONFIRM_HITS and only["age"] == 0.0
    assert 0.5 < only["xyz"][0] < 0.52  # smoothed towards the new measurement, not snapped

    # A different label at the same spot is a second object; the same label far away is a third
    tracker.update([cup, Located("bottle", 0.8, (0.5, 0.0, 0.0), cup.size), Located("cup", 0.8, (1.5, 0.0, 0.0), cup.size)], now=0.2)
    for _ in range(CONFIRM_HITS):
        tracker.update([cup, Located("bottle", 0.8, (0.5, 0.0, 0.0), cup.size), Located("cup", 0.8, (1.5, 0.0, 0.0), cup.size)], now=0.3)
    assert [o["label"] for o in tracker.objects(0.3)] == ["cup", "bottle", "cup"]

    # Out of view: remembered with a growing age, then forgotten
    tracker.update([], now=3.0)
    assert all(abs(o["age"] - 2.7) < 1e-6 for o in tracker.objects(3.0))
    tracker.update([], now=9.0)
    assert tracker.objects(9.0) == []


def test_mock_objects_flow_through_the_hub():
    hub = Hub(Settings(mock=True))
    scene = MockObjects()
    for t in (0.0, 0.1, 0.2):
        hub.on_located(scene.located(t))
    objects = hub.snapshot(True)["objects"]
    assert {o["label"] for o in objects} == {"bottle", "cup", "cell phone", "keyboard", "apple"}
    assert all(set(o) == {"id", "label", "xyz", "size", "confidence", "age", "hits"} for o in objects)
    assert hub.health(True)["topics"]["objects"]["age_ms"] is not None  # counted (hz needs a clock tick to pass)
    # The cup leaves the view during part of the cycle; the rest stay
    away = MockObjects.CYCLE_S - 1.0
    hub.on_located(scene.located(away))
    assert "cup" not in {o.label for o in scene.located(away)}
    assert "cup" in {o["label"] for o in hub.snapshot(True)["objects"]}  # still remembered


def test_the_detector_is_told_to_look_only_for_the_labels_of_the_list():
    pytest.importorskip("ultralytics")
    from app.objects import DETECT_LABELS, YoloDetector

    detector = YoloDetector("yolov8n.pt")
    assert DETECT_LABELS == ["bottle"]
    assert [detector._model.names[index] for index in detector._classes] == DETECT_LABELS
    assert detector.detect(np.zeros((480, 640, 3), np.uint8)) == []


def test_an_object_that_is_not_detected_any_more_is_gone_within_a_second():
    tracker = Tracker()
    cup = Located("bottle", 0.9, (0.5, 0.0, 0.0), (0.08, 0.08, 0.2))
    for now in (0.0, 0.25):
        tracker.update([cup], now)
    tracker.update([], 0.5)
    assert [item["age"] for item in tracker.objects(0.5)] == [0.25], "one missed pass: still there, ageing"
    tracker.update([], 1.3)
    assert tracker.objects(1.3) == []


@pytest.mark.parametrize("rotation,code", [(90, "ROTATE_90_CLOCKWISE"), (180, "ROTATE_180"), (270, "ROTATE_90_COUNTERCLOCKWISE")])
def test_a_box_found_in_the_turned_picture_is_put_back_where_the_camera_saw_it(rotation, code):
    import cv2

    from app.objects import box_before_rotation

    sent = np.zeros((480, 640), np.uint8)
    sent[100:180, 400:460] = 255  # the object, in the picture as the camera sent it
    upright = cv2.rotate(sent, getattr(cv2, code))
    ys, xs = np.nonzero(upright)
    found = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))  # what a detector would report

    assert box_before_rotation(found, rotation, 640, 480) == (400.0, 100.0, 459.0, 179.0)
    assert box_before_rotation(found, 0, 640, 480) == found
