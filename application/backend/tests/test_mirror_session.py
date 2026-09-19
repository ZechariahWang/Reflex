import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.mirror.session import CAPTURE_S, Hand, MirrorSession
from app.mirror.synthetic import hand, image_points

FRAME_S = 1 / 30


def seen(curls: list[float]) -> Hand:
    points = hand(curls)
    return Hand(world=points, image=image_points(points))


class Bench:
    """A session on a fake clock, with a hand state to read and a list of what it published."""

    def __init__(self, state: list[float]) -> None:
        self.published: list[list[float]] = []
        self.session = MirrorSession(Settings(), lambda: state, self.published.append)
        self.now = 100.0

    def show(self, curls: list[float] | None, frames: int = 1) -> dict:
        for _ in range(frames):
            self.now += FRAME_S
            status = self.session.on_hand(None if curls is None else seen(curls), self.now)
        return status

    def capture(self, pose: str, curls: list[float] | None) -> dict:
        self.session.calibrate(pose, self.now)
        return self.show(curls, frames=int(CAPTURE_S / FRAME_S) + 2)

    def calibrate(self) -> dict:
        self.capture("open", [0.0] * 5)
        return self.capture("fist", [1.0] * 5)


def test_nothing_is_published_before_the_calibration():
    bench = Bench(state=[0.0] * 5)
    status = bench.show([0.0] * 5, frames=5)
    assert status["mode"] == "off" and status["calibrated"] is False and status["controller"] is None
    assert len(status["landmarks"]) == 21
    assert bench.published == []


def test_calibrated_session_follows_after_a_match_and_publishes_only_changes():
    bench = Bench(state=[0.0] * 5)
    assert bench.calibrate()["calibrated"] is True
    assert bench.show([1.0] * 5)["mode"] == "frozen"  # still the fist of the capture; the hand is open
    assert bench.published == []

    status = bench.show([0.0] * 5, frames=30)
    assert status["mode"] == "following"
    assert status["controller"] == pytest.approx([0.0] * 5, abs=0.02)

    status = bench.show([0.5, 1.0, 1.0, 0.0, 0.0], frames=60)
    assert status["command"] == pytest.approx([0.5, 1.0, 1.0, 0.0, 0.0], abs=0.02)
    assert bench.published[-1] == pytest.approx(status["command"], abs=0.011)  # the deadband
    count = len(bench.published)
    bench.show([0.5, 1.0, 1.0, 0.0, 0.0], frames=30)
    assert len(bench.published) == count

    assert bench.show(None)["mode"] == "no_hand"
    assert bench.show([0.0] * 5, frames=30)["mode"] == "frozen"
    assert len(bench.published) == count


def test_fist_that_is_no_fist_is_refused():
    bench = Bench(state=[0.0] * 5)
    bench.capture("open", [0.0] * 5)
    status = bench.capture("fist", [0.0, 1.0, 1.0, 1.0, 1.0])
    assert status["calibrated"] is False and status["error"] is not None
    assert bench.calibrate()["error"] is None


def test_capture_without_a_hand_is_refused():
    bench = Bench(state=[0.0] * 5)
    assert bench.capture("open", None)["error"] is not None


def test_new_capture_stops_the_following():
    bench = Bench(state=[0.0] * 5)
    bench.calibrate()
    bench.show([0.0] * 5, frames=30)
    bench.session.calibrate("open", bench.now)
    assert bench.show([0.0] * 5)["mode"] == "off"


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(Settings(mock=True))) as test_client:
        yield test_client


def frames_until(ws, done, timeout_s: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        ws.send_bytes(b"\xff\xd8 any frame: the mock tracker has its own hand")
        status = ws.receive_json()
        if done(status):
            return status
    raise AssertionError(f"never reached, last status {status}")


def test_mock_mirror_calibrates_follows_and_commands_the_hand(client):
    with client.websocket_connect("/ws/mirror") as ws:
        assert frames_until(ws, lambda s: True)["mode"] == "off"
        for pose in ("open", "fist"):
            ws.send_text(json.dumps({"type": "calibrate", "pose": pose}))
            frames_until(ws, lambda s: s["capturing"] == pose)
            status = frames_until(ws, lambda s: s["capturing"] is None)
            assert status["error"] is None
        assert status["calibrated"] is True
        ws.send_text("garbage")
        ws.send_text(json.dumps({"type": "calibrate", "pose": "sideways"}))
        command = frames_until(ws, lambda s: s["mode"] == "following")["command"]
        with client.websocket_connect("/ws/state") as state:
            assert state.receive_json()["command"] == pytest.approx(command, abs=0.2)


def test_second_mirror_client_is_refused(client):
    with client.websocket_connect("/ws/mirror") as first:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/mirror") as second:
                second.receive_json()
        assert frames_until(first, lambda s: True)["mode"] == "off"
    with client.websocket_connect("/ws/mirror") as again:
        assert frames_until(again, lambda s: True)["mode"] == "off"


def test_mirror_refuses_a_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect) as refusal:
        with client.websocket_connect("/ws/mirror", headers={"origin": "http://evil.example"}):
            pass
    assert refusal.value.code == 1008
