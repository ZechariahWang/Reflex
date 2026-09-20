import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.hub import FINGERS, TOPICS
from app.main import create_app


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(Settings(mock=True))) as test_client:
        yield test_client


def test_health(client):
    body = client.get("/api/health").json()
    assert body["mock"] is True and body["ros_connected"] is True
    assert body["rosbridge_url"] == "ws://localhost:9090"
    assert set(body["topics"]) == set(TOPICS)
    assert all(set(entry) == {"hz", "age_ms"} for entry in body["topics"].values())


def test_urdf(client):
    response = client.get("/api/urdf")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/xml")
    assert all(f'name="{finger}_joint"' in response.text for finger in FINGERS)


def test_state_shape_and_command_override(client):
    with client.websocket_connect("/ws/state") as ws:
        message = ws.receive_json()
        assert list(message) == [
            "t",
            "ros_connected",
            "fingers",
            "joints",
            "orientation",
            "state",
            "command",
            "passive",
            "objects",
            "rates",
            "session",
            "movement",
        ]
        assert message["fingers"] == list(FINGERS)
        assert set(message["joints"]) == {f"{finger}_joint" for finger in FINGERS}
        assert message["orientation"] is None
        assert len(message["state"]) == 5 and message["command"] is None
        assert set(message["rates"]) == set(TOPICS)
        assert isinstance(message["objects"], list)

        ws.send_text(json.dumps({"type": "command", "data": [0, 1, 1, 0, 0]}))
        ws.send_text("garbage")
        for _ in range(40):
            message = ws.receive_json()
        assert message["command"] == [0.0, 1.0, 1.0, 0.0, 0.0]
        assert message["state"][1] > 0.95 and message["state"][3] < 0.05


@pytest.mark.parametrize(("camera", "kind"), [("realsense", "color"), ("realsense", "depth"), ("iphone", "color")])
def test_camera_sends_meta_then_jpeg(client, camera, kind):
    with client.websocket_connect(f"/ws/camera/{camera}/{kind}") as ws:
        meta = ws.receive_json()
        assert meta["type"] == "meta"
        assert ({"min_mm", "max_mm"} <= set(meta)) == (kind == "depth")
        while True:
            message = ws.receive()
            if message.get("bytes"):
                assert message["bytes"][:2] == b"\xff\xd8"
                break


@pytest.mark.parametrize("path", ["/ws/state", "/ws/camera/realsense/color", "/ws/camera/iphone/color"])
def test_foreign_origin_is_refused(client, path):
    with pytest.raises(WebSocketDisconnect) as refusal:
        with client.websocket_connect(path, headers={"origin": "http://evil.example"}):
            pass
    assert refusal.value.code == 1008


def test_configured_origin_is_accepted(client):
    with client.websocket_connect("/ws/state", headers={"origin": "http://localhost:3000"}) as ws:
        assert ws.receive_json()["fingers"] == list(FINGERS)


@pytest.mark.parametrize("path", ["/ws/camera/webcam/color", "/ws/camera/iphone/depth"])
def test_unknown_camera_is_refused(client, path):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(path):
            pass


def test_the_phone_endpoints_are_gone(client):
    assert client.get("/api/iphone").status_code == 404
    assert client.post("/api/iphone", json={"host": "usb"}).status_code == 404


def test_passive_request_round_trips_through_the_state(client):
    with client.websocket_connect("/ws/state") as ws:
        assert ws.receive_json()["passive"] is False
        ws.send_text(json.dumps({"type": "passive", "data": True}))
        ws.send_text(json.dumps({"type": "passive", "data": "yes"}))  # not a bool: ignored
        for _ in range(10):
            message = ws.receive_json()
        assert message["passive"] is True
        ws.send_text(json.dumps({"type": "passive", "data": False}))
        for _ in range(10):
            message = ws.receive_json()
        assert message["passive"] is False


def test_meshes_and_linkage_come_from_the_description_package(client):
    stl = client.get("/api/meshes/index_horn.stl")
    assert stl.status_code == 200 and len(stl.content) > 1000
    assert client.get("/api/meshes/..%2Fconfig%2Flinkage.yaml").status_code == 404
    assert client.get("/api/meshes/nope.stl").status_code == 404
    linkage = client.get("/api/linkage").json()
    assert set(linkage) == set(FINGERS)
    assert set(linkage["thumb"]["pivots"]) == {"G0", "G1", "G2", "P", "A", "B", "M", "E", "T", "U"}


def test_mock_objects_appear_in_the_state(client):
    with client.websocket_connect("/ws/state") as ws:
        for _ in range(30):
            objects = ws.receive_json()["objects"]
            if objects:
                break
        assert objects and {"bottle", "apple"} <= {o["label"] for o in objects}
        assert all(len(o["xyz"]) == 3 and len(o["size"]) == 3 and o["age"] >= 0 for o in objects)


def test_camera_keeps_streaming_after_the_client_says_ready(client):
    with client.websocket_connect("/ws/camera/realsense/color") as ws:
        def next_frame() -> bytes:
            while True:
                message = ws.receive()
                if message.get("bytes"):
                    return message["bytes"]

        next_frame()  # streamed freely until the first "ready"
        for _ in range(3):
            ws.send_text("ready")
            assert next_frame()[:2] == b"\xff\xd8"


def test_readiness_gates_one_frame_per_ready_and_forgives_a_lost_one():
    import asyncio
    import time

    from app.main import Readiness

    async def scenario() -> None:
        readiness = Readiness(timeout_s=0.2)
        await asyncio.wait_for(readiness.wait(), 0.05)  # never acknowledged: no gate
        readiness.on_text("ready")
        await asyncio.wait_for(readiness.wait(), 0.05)  # one "ready" = one frame
        started = time.monotonic()
        await readiness.wait()  # no "ready": waits for the timeout, then serves anyway
        assert 0.15 <= time.monotonic() - started < 1.0
        readiness.on_text("ready")
        readiness.on_text("noise")
        await asyncio.wait_for(readiness.wait(), 0.05)

    asyncio.run(scenario())
