import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.omni import make_router
from app.omni_core import QwenClient


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "test-key")
    monkeypatch.setenv("QWEN_BASE_URL", "https://example.invalid/v1")
    flags = {"fresh": True, "age": 10, "passive": False, "mirror": False, "mode": "idle"}
    calls = []
    async def next_frame(seen):
        return seen + 1, SimpleNamespace(data=b"jpeg")
    channel = SimpleNamespace(viewers=0, version=1, next=next_frame)
    hub = SimpleNamespace(
        frames={"realsense": {"color": channel}},
        snapshot=lambda connected: {"passive": flags["passive"], "state": [0]*5},
        camera_meta=lambda *args: {"available": flags["fresh"]},
        health=lambda connected: {"topics": {"hand_state": {"age_ms": flags["age"]}}},
    )
    async def stop():
        calls.append("stop")
    movements = SimpleNamespace(listing=lambda: [{"name": "tune", "error": None}],
                                play=calls.append, status=lambda: {"name": "tune"}, stop=stop)
    def complete(self, content, catalog, history):
        calls.append(content)
        return {"heard": "play tune", "scene": "piano", "reply": "Ready", "movement": "tune"}
    monkeypatch.setattr(QwenClient, "complete", complete)
    app = FastAPI()
    app.include_router(make_router(hub, SimpleNamespace(connected=True), movements,
                                  SimpleNamespace(status=lambda: {"mode": flags["mode"]}),
                                  SimpleNamespace(mock=False), lambda: flags["mirror"]))
    with TestClient(app) as client:
        yield client, flags, calls, channel


def propose(client):
    response = client.post("/api/omni/turn", json={"text": "play tune"})
    assert response.status_code == 200, response.text
    return response.json()["proposal_id"]


def test_proposal_does_not_move_hand_and_execute_is_single_use(rig):
    client, _, calls, channel = rig
    proposal_id = propose(client)
    assert "tune" not in calls
    assert calls[0][1]["type"] == "image_url"
    assert channel.viewers == 0
    assert client.post("/api/omni/execute", json={"proposal_id": proposal_id}).status_code == 200
    assert calls.count("tune") == 1
    assert client.post("/api/omni/execute", json={"proposal_id": proposal_id}).status_code == 409


@pytest.mark.parametrize("key,value", [("fresh", False), ("age", 3000), ("age", None),
                                      ("passive", True), ("mirror", True), ("mode", "replaying")])
def test_execution_checks_live_conditions(rig, key, value):
    client, flags, calls, _ = rig
    proposal_id = propose(client)
    flags[key] = value
    assert client.post("/api/omni/execute", json={"proposal_id": proposal_id}).status_code == 409
    assert "tune" not in calls


def test_stop_invalidates_proposal(rig):
    client, _, calls, _ = rig
    proposal_id = propose(client)
    assert client.post("/api/omni/stop").status_code == 200
    assert "stop" in calls
    assert client.post("/api/omni/execute", json={"proposal_id": proposal_id}).status_code == 409


def test_invalid_camera_and_empty_input(rig):
    client, _, _, _ = rig
    assert client.post("/api/omni/turn", json={"camera": "unknown", "text": "hi"}).status_code == 422
    assert client.post("/api/omni/turn", json={}).status_code == 422


def test_camera_timeout_releases_viewer(rig):
    client, _, _, channel = rig
    async def timeout(seen):
        raise asyncio.TimeoutError
    channel.next = timeout
    assert client.post("/api/omni/turn", json={"text": "hi"}).status_code == 409
    assert channel.viewers == 0


def test_expired_proposal_cannot_execute(rig, monkeypatch):
    client, _, calls, _ = rig
    proposal_id = propose(client)
    later = time.monotonic() + 31
    monkeypatch.setattr("app.omni.time", SimpleNamespace(monotonic=lambda: later))
    assert client.post("/api/omni/execute", json={"proposal_id": proposal_id}).status_code == 409
    assert "tune" not in calls


def test_stop_discards_in_flight_model_reply(rig, monkeypatch):
    client, _, calls, _ = rig
    entered, finish = threading.Event(), threading.Event()
    def complete(*args):
        entered.set()
        assert finish.wait(5)
        return {"heard": "play", "scene": "piano", "reply": "Ready", "movement": "tune"}
    monkeypatch.setattr(QwenClient, "complete", complete)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, "/api/omni/turn", json={"text": "play"})
        assert entered.wait(5)
        try:
            assert client.post("/api/omni/stop").status_code == 200
        finally:
            finish.set()
        assert future.result().status_code == 409
    assert "tune" not in calls
