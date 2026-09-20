"""The MCP tools against a fake console backend (no network, no robot)."""
import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.state = {"ros_connected": True, "state": [0.0] * 5, "command": None, "passive": False, "objects": [],
                      "movement": None, "session": {"mode": "idle"}}

    def request(self, method, url, json=None, timeout=None):
        path = url.removeprefix(server.BACKEND_URL)
        self.calls.append((method, path, json))
        if (method, path) == ("GET", "/api/state"):
            return httpx.Response(200, json=self.state)
        if (method, path) == ("POST", "/api/command"):
            self.state["state"] = self.state["command"] = json["values"]
            return httpx.Response(200, json={"sent": json["values"]})
        if method == "PUT" and path == "/api/movements/mine":
            return httpx.Response(409, json={"detail": "mine was written by hand"})
        if method == "PUT":
            return httpx.Response(200, json={"name": path.rsplit("/", 1)[1], "taught": True, **json})
        return httpx.Response(200, json={})


@pytest.fixture
def backend(monkeypatch):
    fake = FakeBackend()
    monkeypatch.setattr(httpx, "request", fake.request)
    return fake


def call(tool, **arguments):
    return asyncio.run(server.mcp.call_tool(tool, arguments))


def test_the_tools_an_agent_gets():
    names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert names == {"get_hand_state", "move_hand", "list_skills", "read_skill", "teach_skill", "run_skill", "stop_skill", "forget_skill"}


def test_move_hand_sends_the_pose_in_finger_order_and_reports_what_was_measured(backend):
    call("move_hand", thumb=0.1, index=0.2, middle=0.3, ring=0.4, pinky=0.5, wait_s=0)

    assert ("POST", "/api/command", {"values": [0.1, 0.2, 0.3, 0.4, 0.5]}) in backend.calls
    assert server.by_finger(backend.state["state"]) == {"thumb": 0.1, "index": 0.2, "middle": 0.3, "ring": 0.4, "pinky": 0.5}


def test_teach_skill_puts_the_path_to_the_backend_and_run_skill_plays_it(backend):
    steps = [{"pose": [0, 1, 1, 0, 0], "seconds": 1.0}]

    call("teach_skill", name="peace", title="Peace", description="", steps=steps)
    call("run_skill", name="peace", wait=True)

    assert ("PUT", "/api/movements/peace", {"title": "Peace", "description": "", "steps": steps}) in backend.calls
    assert ("POST", "/api/movements/play", {"name": "peace"}) in backend.calls


def test_what_the_backend_refuses_reaches_the_agent_as_words(backend):
    with pytest.raises(ToolError, match="written by hand"):
        call("teach_skill", name="mine", title="", description="", steps=[{"pose": [0] * 5, "seconds": 1}])
