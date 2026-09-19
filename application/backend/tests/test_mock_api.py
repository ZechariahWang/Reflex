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
        assert list(message) == ["t", "ros_connected", "fingers", "joints", "state", "command", "rates"]
        assert message["fingers"] == list(FINGERS)
        assert set(message["joints"]) == {f"{finger}_joint" for finger in FINGERS}
        assert len(message["state"]) == 5 and message["command"] is None
        assert set(message["rates"]) == set(TOPICS)

        ws.send_text(json.dumps({"type": "command", "data": [0, 1, 1, 0, 0]}))
        ws.send_text("garbage")
        for _ in range(40):
            message = ws.receive_json()
        assert message["command"] == [0.0, 1.0, 1.0, 0.0, 0.0]
        assert message["state"][1] > 0.95 and message["state"][3] < 0.05


@pytest.mark.parametrize("kind", ["color", "depth"])
def test_camera_sends_meta_then_jpeg(client, kind):
    with client.websocket_connect(f"/ws/camera/{kind}") as ws:
        meta = ws.receive_json()
        assert meta["type"] == "meta"
        assert ({"min_mm", "max_mm"} <= set(meta)) == (kind == "depth")
        while True:
            message = ws.receive()
            if message.get("bytes"):
                assert message["bytes"][:2] == b"\xff\xd8"
                break


@pytest.mark.parametrize("path", ["/ws/state", "/ws/camera/color", "/ws/camera/depth"])
def test_foreign_origin_is_refused(client, path):
    with pytest.raises(WebSocketDisconnect) as refusal:
        with client.websocket_connect(path, headers={"origin": "http://evil.example"}):
            pass
    assert refusal.value.code == 1008


def test_configured_origin_is_accepted(client):
    with client.websocket_connect("/ws/state", headers={"origin": "http://localhost:3000"}) as ws:
        assert ws.receive_json()["fingers"] == list(FINGERS)
