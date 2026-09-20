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
    shortest = min(seconds for pose, seconds in movement["steps"] if max(pose) > min(pose))
    travel = max(max(pose) - min(pose) for pose, _ in movement["steps"])
    assert shortest + 1e-9 >= travel / 2.0 + 0.1, "the HAL's 2.0 per second (plus its ramp) must fit into the shortest press"


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
    assert during == {"name": "wave", "title": "Wave", "step": 1, "steps": 2} and after is None


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
