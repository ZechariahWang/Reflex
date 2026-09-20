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
