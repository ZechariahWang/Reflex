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
