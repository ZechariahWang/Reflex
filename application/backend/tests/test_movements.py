"""Movement scripts: loaded from a folder, checked, played step by step."""
import asyncio
from pathlib import Path

import pytest

from app.config import Settings
from app.movements import MovementError, Movements, load

REPO_MOVEMENTS = Settings().movements_dir


def script(folder: Path, name: str, body: str) -> Path:
    path = folder / f"{name}.py"
    path.write_text(body)
    return path


def test_hot_cross_buns_presses_index_middle_ring_and_nothing_else():
    movement = load(REPO_MOVEMENTS / "hot_cross_buns.py")

    assert movement["title"] == "Hot cross buns"
    pressed = [max(range(5), key=pose.__getitem__) for pose, _ in movement["steps"] if max(pose) > min(pose)]
    index, middle, ring = 1, 2, 3
    assert pressed == [index, middle, ring] * 2 + [ring] * 4 + [middle] * 4 + [index, middle, ring]
    assert all(pose[0] == pose[4] == min(pose) for pose, _ in movement["steps"]), "thumb and pinky never press"
    presses = [(max(pose) - min(pose), seconds) for pose, seconds in movement["steps"] if max(pose) > min(pose)]
    assert max(depth for depth, _ in presses) >= 0.8, "a quarter note asks for nearly the whole travel"
    for depth, seconds in presses:
        # at the HAL's defaults (max_speed 4.0, max_accel 60) a stroke must ARRIVE in its time, or the
        # quick notes turn around in mid-air and blur into one wobble
        assert depth / 4.0 + 4.0 / 60.0 <= seconds + 1e-9, f"a stroke of {depth:.2f} does not fit into {seconds:.3f} s"
    assert sum(seconds for _, seconds in movement["steps"]) < 13.0, "the whole tune, at ~86 bpm"


def test_a_movement_is_played_step_by_step_and_its_status_shows_the_step(tmp_path):
    script(tmp_path, "wave", "TITLE = 'Wave'\ndef steps():\n    return [([0] * 5, 0.05), ([1, 2, -1, 0.5, 0], 0.05)]\n")
    script(tmp_path, "_helper", "def steps():\n    return []\n")

    async def scenario():
        sent = []
        movements = Movements(tmp_path, sent.append)
        assert [m["title"] for m in movements.listing()] == ["Wave"], "files that start with _ are not movements"
        movements.play("wave")
        await asyncio.sleep(0.02)
        during = movements.status()
        with pytest.raises(MovementError):
            movements.play("wave")
        await asyncio.sleep(0.15)
        return sent, during, movements.status()

    sent, during, after = asyncio.run(scenario())
    assert sent == [[0.0] * 5, [1.0, 1.0, 0.0, 0.5, 0.0]], "values are clamped to 0..1"
    assert during == {"name": "wave", "title": "Wave", "step": 1, "steps": 2, "waiting": False, "not_arrived": 0}
    assert after is None


def test_a_broken_file_is_listed_with_its_error_and_cannot_be_played(tmp_path):
    script(tmp_path, "crash", "def steps():\n    return 1 / 0\n")
    script(tmp_path, "short", "def steps():\n    return [([0, 0, 0], 1.0)]\n")
    script(tmp_path, "forever", "def steps():\n    return [([0] * 5, 99.0)]\n")

    async def scenario():
        movements = Movements(tmp_path, print)
        for name in ("crash", "short", "forever", "missing"):
            with pytest.raises(MovementError):
                movements.play(name)
        return movements.listing()

    errors = {m["name"]: m["error"] for m in asyncio.run(scenario())}
    assert "ZeroDivisionError" in errors["crash"] and "5 values" in errors["short"] and "seconds" in errors["forever"]


def test_stop_ends_a_movement_at_once(tmp_path):
    script(tmp_path, "slow", "def steps():\n    return [([0] * 5, 5.0), ([1] * 5, 5.0)]\n")

    async def scenario():
        sent = []
        movements = Movements(tmp_path, sent.append)
        movements.play("slow")
        await asyncio.sleep(0.02)
        await movements.stop()
        return sent, movements.status(), movements.playing

    assert asyncio.run(scenario()) == ([[0.0] * 5], None, False)


def test_a_taught_path_becomes_a_readable_file_that_plays_and_can_be_taught_again(tmp_path):
    movements = Movements(tmp_path, print)
    steps = [{"pose": [0, 0, 0, 0, 0], "seconds": 0.5}, {"pose": [0.2, 1, 1.4, 0, 0], "seconds": 1}]

    taught = movements.teach("peace_sign", "Peace", "two fingers", steps)

    assert taught["taught"] and taught["title"] == "Peace"
    assert taught["steps"][1] == {"pose": [0.2, 1.0, 1.0, 0.0, 0.0], "seconds": 1.0}, "clamped like any command"
    text = (tmp_path / "peace_sign.py").read_text()
    assert "STEPS = [" in text and "([0.2, 1.0, 1.0, 0.0, 0.0], 1.0)," in text
    assert [m["name"] for m in movements.listing()] == ["peace_sign"]
    movements.teach("peace_sign", "Peace 2", "", steps[:1])  # teaching it again replaces it
    assert movements.read("peace_sign")["title"] == "Peace 2"
    movements.forget("peace_sign")
    assert movements.listing() == []


def test_a_movement_written_by_hand_is_never_replaced_or_deleted_through_the_api(tmp_path):
    script(tmp_path, "mine", "def steps():\n    return [([0] * 5, 1.0)]\n")
    movements = Movements(tmp_path, print)

    for attempt in (lambda: movements.teach("mine", "", "", [([1] * 5, 1.0)]), lambda: movements.forget("mine")):
        with pytest.raises(MovementError, match="by hand"):
            attempt()
    assert not movements.read("mine")["taught"]
    for bad in ("../x", "Caps", "", "a" * 60):
        with pytest.raises(MovementError):
            movements.teach(bad, "", "", [([0] * 5, 1.0)])
    with pytest.raises(MovementError):
        movements.teach("empty", "", "", [])


def test_teach_run_and_command_over_http(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(Settings(mock=True, movements_dir=tmp_path))) as client:
        body = {"title": "Fist", "steps": [{"pose": [1, 1, 1, 1, 1], "seconds": 0.2}]}
        assert client.put("/api/movements/fist", json=body).json()["taught"] is True
        assert client.put("/api/movements/Bad Name", json=body).status_code == 409
        assert client.get("/api/movements/fist").json()["steps"] == [{"pose": [1.0] * 5, "seconds": 0.2}]
        assert client.get("/api/movements/nothing").status_code == 404
        assert client.post("/api/movements/play", json={"name": "fist"}).json()["title"] == "Fist"
        assert client.get("/api/state").json()["movement"]["name"] == "fist"
        assert client.post("/api/command", json={"values": [0, 0.5, 2, 0, 0]}).json() == {"sent": [0.0, 0.5, 1.0, 0.0, 0.0]}
        assert client.post("/api/command", json={"values": [0, 0]}).status_code == 422
        client.post("/api/movements/stop")
        assert client.delete("/api/movements/fist").status_code == 200


def test_the_next_pose_is_not_sent_before_the_hand_has_arrived_at_the_last_one(tmp_path, monkeypatch):
    """Quick notes on slow motors: the step's seconds are over long before the finger is there."""
    script(tmp_path, "trill", "def steps():\n    return [([0, 1, 0, 0, 0], 0.02), ([0] * 5, 0.02), ([0, 1, 0, 0, 0], 0.02)]\n")

    async def scenario():
        measured = [0.0] * 5
        target = [0.0] * 5
        sent = []  # (the pose, where the hand was when it was sent)

        def send(pose):
            sent.append((pose, list(measured)))
            target[:] = pose

        movements = Movements(tmp_path, send, lambda: list(measured))
        movements.play("trill")
        seen_waiting = False
        for _ in range(400):  # a slow hand: 0.02 of the travel per 5 ms
            await asyncio.sleep(0.005)
            measured[:] = [m + max(-0.02, min(0.02, t - m)) for m, t in zip(measured, target)]
            seen_waiting |= bool(movements.status() and movements.status()["waiting"])
            if not movements.playing:
                break
        return sent, seen_waiting

    sent, seen_waiting = asyncio.run(scenario())
    assert [pose[1] for pose, _ in sent] == [1.0, 0.0, 1.0]
    assert sent[1][1][1] >= 0.96, "the key was DOWN when the release was sent"
    assert sent[2][1][1] <= 0.04, "and the finger was back UP when the next stroke was sent"
    assert seen_waiting


def test_a_finger_that_cannot_arrive_does_not_hold_the_movement_for_ever(tmp_path, monkeypatch):
    import app.movements as module

    monkeypatch.setattr(module, "ARRIVE_TIMEOUT_S", 0.1)
    script(tmp_path, "push", "def steps():\n    return [([1] * 5, 0.02), ([0] * 5, 0.02)]\n")

    async def scenario():
        sent, last = [], {}
        movements = Movements(tmp_path, sent.append, lambda: [0.0] * 5)  # blocked: the hand never moves
        movements.play("push")
        for _ in range(100):
            await asyncio.sleep(0.01)
            last = movements.status() or last
            if not movements.playing:
                break
        return sent, last

    sent, last = asyncio.run(scenario())
    assert sent == [[1.0] * 5, [0.0] * 5], "it went on after the timeout"
    assert last["not_arrived"] == 1, "and the status counted the step that did not arrive"
