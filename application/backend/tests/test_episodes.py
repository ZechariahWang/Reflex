"""Record from the hub, play back into it: the console's own episode format."""
import asyncio
import json
import shutil

import pytest

from app.config import Settings
from app.episodes import EpisodeError, Episodes, read_frames
from app.hub import Hub
from tests.test_hub import HEAD_JPEG


async def recorded(tmp_path, seconds=0.25, keep=True):
    hub = Hub(Settings())
    hub.bind(asyncio.get_running_loop())
    sent = []
    episodes = Episodes(tmp_path, hub, sent.append)
    hub.on_hand_state([0.1, 0.2, 0.3, 0.4, 0.5])
    hub.on_head_color(HEAD_JPEG)
    episodes.start_recording("grasp", "pick the bottle")
    await asyncio.sleep(seconds / 2)
    hub.on_hand_command([1.0, 1.0, 0.0, 0.0, 0.0])
    await asyncio.sleep(seconds / 2)
    await episodes.stop(keep)
    return hub, episodes, sent


def test_a_recording_has_state_the_last_command_as_action_and_each_new_jpeg_once(tmp_path):
    hub, episodes, _ = asyncio.run(recorded(tmp_path))

    (dataset,) = episodes.datasets()
    assert dataset["name"] == "grasp" and dataset["task"] == "pick the bottle" and len(dataset["episodes"]) == 1
    frames = read_frames(tmp_path / "grasp" / "episode_000")
    assert 5 <= len(frames) <= 9, "30 fps for a quarter of a second"
    assert frames[0]["state"] == [0.1, 0.2, 0.3, 0.4, 0.5]
    assert frames[0]["action"] == frames[0]["state"], "nobody has commanded yet: the action is the state"
    assert frames[-1]["action"] == [1.0, 1.0, 0.0, 0.0, 0.0]
    assert frames[-1]["camera1"] == "camera1/000000.jpg" and frames[-1]["camera2"] is None
    assert [p.name for p in (tmp_path / "grasp" / "episode_000" / "camera1").iterdir()] == ["000000.jpg"]
    assert episodes.status() == {"mode": "idle"}


def test_a_discarded_recording_leaves_nothing_and_the_next_one_takes_its_number(tmp_path):
    _, episodes, _ = asyncio.run(recorded(tmp_path, keep=False))

    assert episodes.datasets()[0]["episodes"] == []
    assert not (tmp_path / "grasp" / "episode_000").exists()


def test_a_recording_after_a_deleted_episode_keeps_the_episodes_that_are_left(tmp_path):
    async def scenario():
        _, episodes, _ = await recorded(tmp_path)
        episodes.start_recording("grasp", "")
        await asyncio.sleep(0.1)
        await episodes.stop()
        kept = read_frames(tmp_path / "grasp" / "episode_001")
        shutil.rmtree(tmp_path / "grasp" / "episode_000")  # a person removes a bad episode
        episodes.start_recording("grasp", "")
        await asyncio.sleep(0.1)
        await episodes.stop()
        return kept

    kept = asyncio.run(scenario())
    assert read_frames(tmp_path / "grasp" / "episode_001") == kept
    assert (tmp_path / "grasp" / "episode_002" / "frames.jsonl").is_file()


def test_a_replay_commands_the_hand_and_owns_the_camera_panels(tmp_path):
    async def scenario():
        hub, episodes, sent = await recorded(tmp_path)
        sent.clear()
        hub.frames["iphone"]["color"].latest = None
        episodes.start_replay("grasp", 0, speed=4.0)
        await asyncio.sleep(0.02)
        assert episodes.status()["mode"] == "replaying" and hub.replaying
        hub.on_head_color(b"live frame")  # the live camera must not flicker into the replay
        with pytest.raises(EpisodeError):
            episodes.start_recording("grasp", "")
        await asyncio.sleep(0.3)
        return hub, episodes, sent

    hub, episodes, sent = asyncio.run(scenario())

    frames = read_frames(tmp_path / "grasp" / "episode_000")
    assert sent == [frame["action"] for frame in frames]
    assert hub.frames["iphone"]["color"].latest.data == HEAD_JPEG
    assert episodes.status() == {"mode": "idle"} and not hub.replaying


def test_names_cannot_leave_the_recordings_folder(tmp_path):
    async def scenario():
        hub = Hub(Settings())
        with pytest.raises(EpisodeError):
            Episodes(tmp_path, hub, print).start_recording("../outside", "")
        with pytest.raises(EpisodeError):
            Episodes(tmp_path, hub, print).start_replay("nothing", 0)

    asyncio.run(scenario())


def test_the_page_records_lists_and_replays_over_the_api(tmp_path):
    import time

    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(Settings(mock=True, recordings_dir=tmp_path))) as client:
        assert client.get("/api/episodes").json() == {"session": {"mode": "idle"}, "datasets": []}
        assert client.post("/api/episodes/record", json={"dataset": "grasp", "task": "bottle"}).json()["mode"] == "recording"
        assert client.post("/api/episodes/record", json={"dataset": "grasp"}).status_code == 409, "one at a time"
        time.sleep(0.3)
        listing = client.post("/api/episodes/stop", json={"keep": True}).json()
        assert listing["session"] == {"mode": "idle"} and listing["datasets"][0]["episodes"][0] >= 5
        assert client.post("/api/episodes/replay", json={"dataset": "grasp", "episode": 3}).status_code == 409
        replay = client.post("/api/episodes/replay", json={"dataset": "grasp", "episode": 0, "what": "state"}).json()
        assert replay["mode"] == "replaying" and replay["frames"] == listing["datasets"][0]["episodes"][0]
        with client.websocket_connect("/ws/state", headers={"origin": "http://localhost:3000"}) as ws:
            assert json.loads(ws.receive_text())["session"]["mode"] == "replaying"
        client.post("/api/episodes/stop", json={})
