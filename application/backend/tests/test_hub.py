import pytest
import asyncio

from app.config import Settings
from app.hub import FINGERS, Hub
from app.mock import encode_compressed_depth
from tests.test_depth import synthetic

# Only a start-of-frame header (640 x 480): the hub must not decode or re-encode the image.
HEAD_JPEG = bytes.fromhex("ffd8" "ffc0" "0011" "08" "01e0" "0280" "03" "012200" "021101" "031101")


def test_malformed_ros_vectors_are_ignored_but_counted():
    hub = Hub(Settings())
    hub.on_hand_state([0.1, 0.2, 0.3, 0.4, 0.5])
    for bad in ([0.1, 0.2, 0.3], [0.1, None, 0.3, 0.4, 0.5], [0.1, float("nan"), 0.3, 0.4, 0.5]):
        hub.on_hand_state(bad)
        hub.on_hand_command(bad)
    snapshot = hub.snapshot(True)
    assert snapshot["state"] == [0.1, 0.2, 0.3, 0.4, 0.5] and snapshot["command"] is None
    assert hub.health(True)["topics"]["hand_state"]["age_ms"] is not None


def test_joint_states_keep_only_finite_finger_joints():
    hub = Hub(Settings())
    hub.on_joint_states(["world_mount", "pinky_joint", "thumb_joint"], [9.0, 0.5, None])
    joints = hub.snapshot(True)["joints"]
    assert set(joints) == {f"{finger}_joint" for finger in FINGERS}
    assert joints["pinky_joint"] == 0.5 and joints["thumb_joint"] == 0.0


def test_orientation_keeps_only_finite_imu_quaternions():
    hub = Hub(Settings())
    assert hub.snapshot(True)["orientation"] is None

    hub.on_orientation({"x": 0.0, "y": 0.0, "z": float("nan"), "w": 1.0})
    assert hub.snapshot(True)["orientation"] is None

    hub.on_orientation({"x": 0.1, "y": 0.2, "z": 0.3, "w": 0.9})
    assert hub.snapshot(True)["orientation"] == {"x": 0.1, "y": 0.2, "z": 0.3, "w": 0.9}


def test_imu_without_orientation_falls_back_to_accelerometer_tilt():
    hub = Hub(Settings())
    hub.on_imu({
        "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 0.0},
        "linear_acceleration": {"x": 0.0, "y": 0.0, "z": 9.81},
    })
    assert hub.snapshot(True)["orientation"] == {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def test_head_jpeg_reaches_the_iphone_color_channel_untouched():
    async def scenario() -> Hub:
        hub = Hub(Settings())
        hub.bind(asyncio.get_running_loop())
        hub.on_head_color(HEAD_JPEG)
        await asyncio.sleep(0)
        return hub

    hub = asyncio.run(scenario())
    frame = hub.frames["iphone"]["color"].latest
    assert frame is not None and frame.data is HEAD_JPEG
    assert (frame.width, frame.height) == (640, 480)
    assert hub.health(True)["topics"]["iphone"]["age_ms"] is not None
    assert "depth" not in hub.frames["iphone"]


def test_depth_worker_survives_a_bad_frame():
    async def scenario() -> bool:
        hub = Hub(Settings())
        hub.bind(asyncio.get_running_loop())
        worker = asyncio.create_task(hub.run_depth_worker())
        hub.frames["realsense"]["depth"].viewers = 1
        hub.on_depth(bytes(12))
        await asyncio.sleep(0.1)
        hub.on_depth(encode_compressed_depth(synthetic()))
        await asyncio.sleep(0.3)
        alive = not worker.done()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        return alive and hub.frames["realsense"]["depth"].latest is not None

    assert asyncio.run(scenario())


class CupInTheMiddle:
    def detect(self, bgr):
        from app.objects import Detection

        return [Detection("cup", 0.9, (280.0, 200.0, 360.0, 280.0))]


def detected_labels(monkeypatch, feed) -> list[str]:
    """Run the object worker on a fake detector for a moment; `feed(hub)` gives it its frames."""
    import cv2
    import numpy as np

    monkeypatch.setattr("app.hub.make_detector", lambda model, threads: CupInTheMiddle())
    jpeg = cv2.imencode(".jpg", np.zeros((480, 640, 3), np.uint8))[1].tobytes()
    depth = encode_compressed_depth(np.full((480, 640), 600, np.uint16))

    async def scenario() -> Hub:
        hub = Hub(Settings())
        hub.bind(asyncio.get_running_loop())
        worker = asyncio.create_task(hub.run_object_worker("fake", max_hz=0))
        for _ in range(4):  # CONFIRM_HITS detections in a row before a track is reported
            feed(hub, jpeg, depth)
            await asyncio.sleep(0.05)
        worker.cancel()
        return hub

    return [item["label"] for item in asyncio.run(scenario()).snapshot(True)["objects"]]


def test_with_no_wrist_camera_the_detector_takes_the_head_camera_and_its_depth(monkeypatch):
    def only_the_phone(hub, jpeg, depth):
        hub.on_head_depth(depth)
        hub.on_head_color(jpeg)

    assert detected_labels(monkeypatch, only_the_phone) == ["cup"]


def test_the_head_camera_without_depth_places_nothing(monkeypatch):
    assert detected_labels(monkeypatch, lambda hub, jpeg, depth: hub.on_head_color(jpeg)) == []


def test_while_the_wrist_camera_runs_the_head_camera_is_not_detected_in(monkeypatch):
    def both(hub, jpeg, depth):
        hub.on_color(jpeg)  # the wrist camera runs, but has no depth yet: nothing can be placed ...
        hub.on_head_depth(depth)
        hub.on_head_color(jpeg)  # ... and the phone, which could be, must not take over

    assert detected_labels(monkeypatch, both) == []


def test_the_detector_sees_the_wrist_picture_upright_and_the_object_lands_where_the_camera_saw_it(monkeypatch):
    import cv2
    import numpy as np

    seen = {}

    class CupAtTheTopOfTheUprightPicture:
        def detect(self, bgr):
            from app.objects import Detection

            seen["shape"] = bgr.shape
            return [Detection("cup", 0.9, (200.0, 40.0, 280.0, 120.0))]  # upright: 480 wide, 640 high

    monkeypatch.setattr("app.hub.make_detector", lambda model, threads: CupAtTheTopOfTheUprightPicture())
    jpeg = cv2.imencode(".jpg", np.zeros((480, 640, 3), np.uint8))[1].tobytes()
    depth = np.zeros((480, 640), np.uint16)
    depth[180:300, 20:140] = 500  # only where that box is in the picture AS SENT (turned back from 90 cw)

    async def scenario() -> Hub:
        hub = Hub(Settings(realsense_rotation=90))
        hub.bind(asyncio.get_running_loop())
        worker = asyncio.create_task(hub.run_object_worker("fake", max_hz=0))
        for _ in range(4):
            hub.on_depth(encode_compressed_depth(depth))
            hub.on_color(jpeg)
            await asyncio.sleep(0.05)
        worker.cancel()
        return hub

    hub = asyncio.run(scenario())
    assert seen["shape"] == (640, 480, 3), "the detector got a portrait picture"
    (cup,) = hub.snapshot(True)["objects"]
    assert cup["xyz"][0] == pytest.approx(0.5, abs=0.01), "placed with the depth under the box turned back"
    assert hub.camera_meta("realsense", "color")["rotation"] == 90 and "rotation" not in hub.camera_meta("iphone", "color")


def test_blocked_fingers_from_the_hal_show_in_the_state():
    hub = Hub(Settings())
    assert hub.snapshot(True)["blocked"] == [False] * 5
    hub.on_blocked([0.0, 0.0, 1.0, 0.0, 0.0])
    assert hub.snapshot(True)["blocked"] == [False, False, True, False, False]
    hub.on_blocked([1.0])  # not 5 values: ignored
    assert hub.snapshot(True)["blocked"] == [False, False, True, False, False]


def test_motor_currents_show_as_the_peak_of_the_last_half_second(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.hub.time.monotonic", lambda: clock[0])
    hub = Hub(Settings())
    assert hub.snapshot(True)["current"] is None  # the sim has no current
    hub.on_current([26.0, 26.0, 260.0, 26.0, 26.0])  # one cycle of a peak ...
    clock[0] += 0.3
    hub.on_current([26.0, 26.0, 40.0, 26.0, 26.0])
    assert hub.snapshot(True)["current"] == [26.0, 26.0, 260.0, 26.0, 26.0]  # ... stays readable
    clock[0] += 0.3
    hub.on_current([26.0, 26.0, 40.0, 26.0, 26.0])
    assert hub.snapshot(True)["current"] == [26.0, 26.0, 40.0, 26.0, 26.0]



def test_the_policy_is_offline_until_its_heartbeat_and_again_after_three_silent_seconds(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.hub.time.monotonic", lambda: clock[0])
    hub = Hub(Settings())
    assert hub.snapshot(True)["policy"] == "offline"
    hub.on_policy_active(False)
    assert hub.snapshot(True)["policy"] == "ready"
    hub.on_policy_active(True)
    assert hub.snapshot(True)["policy"] == "running"
    clock[0] += 3.5
    assert hub.snapshot(True)["policy"] == "offline"
